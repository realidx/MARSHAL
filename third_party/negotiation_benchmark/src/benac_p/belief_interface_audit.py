"""Small discovery-only wording x tool-availability audit, without changing diagnosis."""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import random

from benac_p.diagnose_protocol import generate, parse_completion, submission_tool, system_prompt, protocol_summary
from benac_p.diagnose_suite import digest, dump
from benac_p.reasoning_calibration import evaluate
from benac_p.semantic_suite import SYSTEM, Suite

VERSION = 'belief-interface-audit-v1'
CLEAR_QUESTION = (
    "Which preferences remain possible for P1's first assessment in this episode, given "
    "initially_possible_preferences and history? The initially_possible_preferences field "
    "is supplied prior information for this episode, not a list of output labels. "
    "Submit exactly the supported subset in possible_preferences. Preserve uncertainty "
    "only when the supplied information does not distinguish alternatives."
)
VARIANTS = ('original_auto', 'clear_auto', 'original_staged', 'clear_staged')


def prepare(source, bundles=2):
    manifest = json.loads((source/'manifest.json').read_text())
    archive = json.loads((source/'tasks.json').read_text())
    answers = json.loads((source/'answers.json').read_text())
    if manifest.get('oracle_check') or manifest.get('reasoning_profile') != 'balanced':
        raise ValueError('Use a real balanced semantic run.')
    if archive['system'] != system_prompt(SYSTEM, 'reasoning_tools', 'balanced'):
        raise ValueError('Source system prompt differs from current baseline.')
    suite = Suite(manifest['bundles'], manifest['seed']).build()
    if digest(suite.tasks) != manifest['task_hash']:
        raise ValueError('Source tasks differ from current generator.')
    if not 1 <= bundles <= manifest['bundles']//2:
        raise ValueError('Select only available discovery bundles.')
    chosen = {f"b{manifest['seed']+i}" for i in range(bundles)}
    rows = []
    for task in suite.tasks:
        label = suite.labels[task['id']]
        if task['kind'] != 'semantic_belief' or label['bundle'] not in chosen:
            continue
        if label['condition'] not in ('known', 'unknown_relevant'):
            continue
        root = label['case'].endswith('/root')
        if label['condition'] == 'known' and not root:
            continue
        payload = suite.payload(task, {})
        baseline = answers[task['id']]
        if baseline.get('payload_hash') != digest(payload):
            raise ValueError('Archived payload fingerprint mismatch.')
        if baseline.get('status') not in ('ok', 'invalid', 'truncated') or baseline.get('finalization_attempted'):
            raise ValueError('Selected baseline must be an unrecovered completed first pass.')
        rows.append(dict(id=task['id'], task=task, payload=payload, baseline=baseline,
                         expected={'possible_preferences': label['possible_preferences']},
                         category=('known_copy' if label['condition']=='known' else 'unresolved_prior') if root else 'evidence_update'))
    return manifest, rows


def request(client, row, variant):
    payload = deepcopy(row['payload'])
    if variant.startswith('clear'):
        payload['question'] = CLEAR_QUESTION
    if variant.endswith('auto'):
        return generate(client, row['task'], payload, SYSTEM, reasoning_profile='balanced', finalization_tokens=128)
    # Same task and initial cap, but no tools are exposed until the submission turn.
    messages = [{'role': 'system', 'content': system_prompt(SYSTEM, 'reasoning_tools', 'balanced') +
                 '\nFor this request, the submission tool is not available yet. Briefly reason about the question in ordinary text. '
                 'You will submit through the tool on the next turn; do not format a tool call now.'},
                {'role': 'user', 'content': json.dumps(payload)}]
    completion = client.complete_response(messages)
    first = dict(status='truncated' if completion.finish_reason=='length' else 'reasoning_complete',
                 raw=completion.content, raw_message=dict(completion.raw_message),
                 reasoning=completion.content, reasoning_present=bool(completion.content.strip()),
                 reasoning_word_count=len(completion.content.split()), usage=dict(completion.usage),
                 finish_reason=completion.finish_reason, response_protocol='reasoning_tools', reasoning_profile='balanced')
    if completion.content:
        messages.append({'role': 'assistant', 'content': completion.content})
    messages.append({'role': 'user', 'content': 'The submission tool is now available. Submit your best final answer using this tool only; do not add further analysis.'})
    tool = submission_tool(row['task'])
    try:
        last = parse_completion(client.complete_with_tools(messages, tools=[tool],
            tool_choice={'type': 'function', 'function': {'name': tool['function']['name']}},
            parallel_tool_calls=False, max_tokens=128), tool, 'reasoning_tools', 'balanced')
    except Exception as exc:
        last = dict(status='transport_error', error=type(exc).__name__, usage={})
    record = dict(last, attempts=[first, last], first_pass_status=first['status'],
                  reasoning=first['reasoning'], reasoning_present=first['reasoning_present'],
                  reasoning_word_count=first['reasoning_word_count'], response_protocol='reasoning_tools',
                  reasoning_profile='balanced', interface='staged', submission_tokens=128)
    if last['status']=='transport_error':record['status']='submission_error'
    record['usage'] = {key: sum(r.get('usage', {}).get(key, 0) for r in (first, last))
                       for key in ('prompt_tokens', 'completion_tokens', 'total_tokens')
                       if any(key in r.get('usage', {}) for r in (first, last))}
    return record


def report(rows, records, out):
    result = {}
    lines = ['# Belief interface audit', '',
             'Discovery-only development comparison; original auto is cached. Staged means one text-only reasoning call followed by a 128-token named-tool submission. '
             'It changes the elicitation protocol and does not prove that generated reasoning is faithful.', '',
             '| Variant / category | N | Valid | Reasoning present | Exact | Returns all three |',
             '|---|---:|---:|---:|---:|---:|']
    for variant in VARIANTS:
        result[variant] = {}
        for category in ('known_copy', 'unresolved_prior', 'evidence_update'):
            selected = [r for r in rows if r['category']==category and variant+'/'+r['id'] in records]
            if not selected:continue
            rr = [records[variant+'/'+r['id']] for r in selected]
            scores = [evaluate(row, record) for row, record in zip(selected, rr)]
            n = len(rr)
            item = dict(n=n, valid=sum(s['valid'] for s in scores)/n,
                        exact=sum(s['success'] for s in scores)/n,
                        reasoning_present=sum(r.get('reasoning_present', False) for r in rr)/n,
                        all_three=sum(set(r.get('answer', {}).get('possible_preferences', []))=={'want','neutral','avoid'} for r in rr)/n)
            result[variant][category] = item
            lines.append(f"| {variant} / {category} | {n} | {item['valid']:.0%} | {item['reasoning_present']:.0%} | {item['exact']:.0%} | {item['all_three']:.0%} |")
        result[variant]['protocol'] = protocol_summary({r['id']: records[variant+'/'+r['id']] for r in rows if variant+'/'+r['id'] in records})
    lines += ['', 'Inspect known-copy behavior before attributing evidence-update failures specifically to partner inference. '
              'A correct unresolved-prior answer can be produced by copying all labels; do not use pooled accuracy alone to select a prompt. '
              'Neither wording nor staging exposes oracle answers. No main-suite prompt has been changed.']
    dump(out/'comparison.json', result)
    (out/'report.md').write_text('\n'.join(lines)+'\n')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-run', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--bundles', type=int, default=2)
    parser.add_argument('--base-url', default='http://localhost:8000/v1')
    parser.add_argument('--model', default='Qwen/Qwen3-4B-Instruct-2507')
    parser.add_argument('--export-only', action='store_true')
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args(argv)
    source, out = args.source_run.resolve(), args.output_dir.resolve()
    if out==source or source in out.parents:parser.error('Keep output outside the source archive.')
    manifest, rows = prepare(source, args.bundles)
    if args.model != manifest['model']:parser.error('Use the same model as the archived baseline.')
    out.mkdir(parents=True, exist_ok=True)
    config = dict(version=VERSION, source_hash=digest([manifest, rows]), model=args.model,
                  base_url=args.base_url, question=CLEAR_QUESTION, variants=list(VARIANTS),
                  initial_tokens=manifest['max_tokens'], submission_tokens=128)
    if (out/'manifest.json').exists():
        if json.loads((out/'manifest.json').read_text())!=config:parser.error('Changed audit; use a fresh directory.')
        if (out/'answers.json').exists() and not args.resume:parser.error('Use --resume for existing answers.')
    elif args.resume:parser.error('No audit manifest to resume.')
    dump(out/'manifest.json', config)
    dump(out/'tasks.json', [{k:v for k,v in r.items() if k not in ('expected','baseline')} for r in rows])
    dump(out/'oracle_labels.json', {r['id']:r['expected'] for r in rows})
    records = json.loads((out/'answers.json').read_text()) if (out/'answers.json').exists() else {}
    for r in rows:records.setdefault('original_auto/'+r['id'], r['baseline'])
    dump(out/'answers.json', records)
    jobs = [(v,r) for v in VARIANTS[1:] for r in rows if v+'/'+r['id'] not in records]
    random.Random(0).shuffle(jobs)
    if args.export_only:
        report(rows, records, out)
        print(f'{len(rows)} frozen questions; {len(jobs)} new task pipelines; normally {5*len(rows)} new HTTP calls, at most {6*len(rows)} including auto truncation recovery.')
        return
    from methods.vllm_client import OpenAICompatibleNegotiationClient
    client = OpenAICompatibleNegotiationClient(args.base_url,args.model,
        api_key=os.environ.get('BENAC_P_VLLM_API_KEY','EMPTY'),max_tokens=manifest['max_tokens'],temperature=manifest['temperature'])
    for variant, row in jobs:
        # First-request transport errors stop here; saved completed tasks are resumable.
        record = request(client, row, variant)
        if record['status']=='ok' and not evaluate(row, record)['valid']:
            record.update(status='invalid', error='Invalid semantic preference set.')
        records[variant+'/'+row['id']] = record
        dump(out/'answers.json', records)
        print(variant, row['id'], record['status'], flush=True)
    report(rows, records, out)
    print(f"Audit report: {out/'report.md'}")


if __name__ == '__main__':main()
