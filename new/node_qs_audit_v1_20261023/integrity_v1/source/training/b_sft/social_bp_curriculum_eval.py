"""Leak-free requests, strict set rewards, and per-skill group diagnostics.

Export requests or score externally collected native tool-call responses. This
module does not start a model server, train, or silently call a remote endpoint.
"""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
import random
import os
from queue import Queue, Empty
from threading import Lock

from jsonschema import validate, ValidationError

from training.b_sft.social_bp_curriculum import RULES, VERSION, digest
from training.b_sft.social_b_oracle import canonical
from training.b_sft.social_lm_eval import tool_for


def request(task, *, prior_turns=(), max_tokens=1024):
    if type(max_tokens) is not int or not 0 < max_tokens <= 4096:
        raise ValueError('Positive response budget up to 4096 required')
    rules = RULES
    if task['input'].get('game', {}).get('variant') == 'social-private-investigate-per-player-v1':
        # Preserve the ordinary native game rules, replace the old public/shared
        # investigation contract only for explicitly versioned private tasks.
        rules = RULES.split('INVESTIGATE selects', 1)[0] + (
            'INVESTIGATE selects another player and a goal. The query actor and target are public; '
            'only the investigator receives that one TRUE preference. Each player has one use per game. '
            'It consumes the current proposal turn without changing commitments. Known or irrelevant '
            'preferences remain legal targets: a poor target still returns the truth and spends the use. '
            'Other players know their own preferences and their own private query results, not yours. '
            'Public behavior can provide indirect evidence. No MENU is available. '
            'Preference rows follow the displayed goal order.')
    messages = [dict(role='system',content=rules+' Numeric preference entries -1/0/1 mean avoid/neutral/want. '
        'Give a concise explanation and exactly one native submission tool call. '
        'Only submit the requested belief or action, without numerical confidence estimates.')]
    last_length = -1
    for prior in prior_turns:
        previous = prior['task']
        a, b = previous['input'], task['input']
        if (task['task'] != 'B' or previous['task'] != 'B' or previous['source'] != task['source']
            or a['queries'] != b['queries'] or a['observer'] != b['observer']
            or len(a['history']) >= len(b['history']) or b['history'][:len(a['history'])] != a['history']
            or previous['skill'] != 'formation' or task['skill'] != 'formation'):
            raise ValueError('Sequences require formation checkpoints along the same actual history')
        if len(a['history']) <= last_length:
            raise ValueError('Sequence must be chronological')
        last_length = len(a['history'])
        messages.append(dict(role='user',content=json.dumps(a,ensure_ascii=False)))
        message = deepcopy(prior['raw_message'])
        if message.get('role') != 'assistant':
            raise ValueError('An actual prior assistant message is required')
        messages.append(message)
        for call in message.get('tool_calls') or []:
            messages.append(dict(role='tool',tool_call_id=call['id'],content='Recorded.'))
    messages.append(dict(role='user',content=json.dumps(task['input'],ensure_ascii=False)))
    return dict(messages=messages,tools=[tool_for(task['task'],task['input'])],
                tool_choice='auto',parallel_tool_calls=False,max_tokens=max_tokens)


def score(task, completion):
    if completion.get('status') == 'infrastructure_failure':
        return dict(status='infrastructure_failure',reward=None,correct=None)
    if completion.get('finish_reason') == 'length':
        return dict(status='truncated',reward=-1,correct=False)
    tool = tool_for(task['task'],task['input'])['function']
    try:
        calls = completion['raw_message'].get('tool_calls',[])
        if len(calls) != 1 or calls[0]['function']['name'] != tool['name']:
            raise ValueError('Exactly one native submission required')
        args = json.loads(calls[0]['function']['arguments'])
        validate(args,tool['parameters'])
        if task['task'] == 'B':
            pred = args['judgments'][0]
            target = task['teacher']['gold']
            ps, gs = set(pred['possible_preferences']), set(target['possible_preferences'])
            if pred['favored'] != 'undetermined' and pred['favored'] not in ps:
                raise ValueError('Favored must remain possible')
            if len(ps) == 1 and pred['favored'] not in ps:
                raise ValueError('Singleton must favor its sole member')
            correct = ps == gs and pred['favored'] == target['favored']
            details = dict(set_exact=ps==gs,favored_exact=pred['favored']==target['favored'],
                false_exclusions=len(gs-ps),extra_possibilities=len(ps-gs),
                predicted_full_set=ps=={'want','neutral','avoid'})
        else:
            if canonical(args) not in {canonical(a) for a in task['input']['legal_actions']}:
                raise ValueError('Not an exact displayed legal action')
            correct = canonical(args) in {canonical(a) for a in task['teacher']['acceptable_actions']}
            details = dict(investigated=args.get('action')=='INVESTIGATE')
        return dict(status='ok',reward=int(correct),correct=correct,**details)
    except (KeyError,TypeError,ValueError,ValidationError) as exc:
        return dict(status='format_failure',reward=-1,correct=False,reason=type(exc).__name__)


def group_diagnostics(tasks, samples, *, group_size=8):
    """A sample row contains task_id, sample_index and an original completion.

    No retries mixed into groups, no missing samples silently dropped. Binary
    success diversity and actual reward diversity differ when formatting fails.
    """
    if type(group_size) is not int or group_size < 2:
        raise ValueError('At least two independent samples per group required')
    by_id = {t['id']:t for t in tasks}
    groups = defaultdict(dict)
    for sample in samples:
        tid, index = sample['task_id'], sample['sample_index']
        if tid not in by_id or type(index) is not int or not 0 <= index < group_size:
            raise ValueError('Unknown task or invalid sample index')
        if index in groups[tid]:
            raise ValueError('Duplicate sample; retries are not independent samples')
        groups[tid][index] = score(by_id[tid], sample)
    details, buckets = [], defaultdict(list)
    for tid, t in by_id.items():
        scored = list(groups[tid].values())
        usable = [r for r in scored if r['reward'] is not None]
        if len(usable) != group_size:
            status = 'incomplete'
        else:
            successes = sum(r['correct'] for r in usable)
            status = 'all_correct' if successes == group_size else 'all_wrong' if successes == 0 else 'mixed'
        row = dict(task_id=tid,status=status,received=len(scored),evaluable=len(usable),
            successes=sum(r['correct'] for r in usable),
            reward_diverse=len({r['reward'] for r in usable}) > 1 if status != 'incomplete' else None,
            statuses=dict(Counter(r['status'] for r in scored)),
            false_exclusions=sum(r.get('false_exclusions',0) for r in usable),
            extra_possibilities=sum(r.get('extra_possibilities',0) for r in usable),
            full_set_predictions=sum(r.get('predicted_full_set',False) for r in usable))
        details.append(row)
        buckets[(t['split'],t['task'],t['stage'],t.get('category',t['skill']))].append(row)
    strata = []
    for (split,task,stage,skill), rows in sorted(buckets.items()):
        counts = Counter(r['status'] for r in rows)
        action = ('collect_samples' if counts['incomplete'] else
                  'add_shorter_bridge_and_keep_core_probes' if counts['all_wrong'] == len(rows) else
                  'reduce_frequency_keep_review' if counts['all_correct'] == len(rows) else 'practice')
        strata.append(dict(split=split,task=task,stage=stage,skill=skill,groups=dict(counts),
            reward_diverse_groups=sum(r['reward_diverse'] is True for r in rows),recommendation=action,
            false_exclusions=sum(r['false_exclusions'] for r in rows),
            extra_possibilities=sum(r['extra_possibilities'] for r in rows),
            full_set_predictions=sum(r['full_set_predictions'] for r in rows)))
    return dict(group_size=group_size,groups=details,strata=strata,
                supplied_samples=len(samples),model_sampling_provenance_verified=False,eval_steps=10,
                caution='Difficulty is estimated only from complete independent groups. All-wrong skills remain represented; never auto-drop them.')


def select_batch(tasks, *, task, stage, size, seed, diagnostics=None):
    """Separate B/P practice; sample fresh completions when repeating a prompt.

    Rotate across skill strata before adapting within a stratum. All-wrong
    prompts retain nonzero weight; fully solved prompts retain review weight.
    Protocol-only all-accepted P items never dominate capability training.
    """
    if task not in ('B','P') or stage not in (0,1,2) or type(size) is not int or size < 1:
        raise ValueError('Specify B/P, stage 0..2, and positive batch size')
    eligible = [t for t in tasks if t['task']==task and t['split']=='train' and t['stage']<=stage
                and not t['teacher'].get('all_legal_accepted',False)]
    if not eligible:
        raise ValueError('No supervised examples at this stage')
    buckets = defaultdict(list)
    for t in eligible:
        buckets[(t['stage'],t.get('category',t['skill']))].append(t)
    rng = random.Random(seed)
    keys = sorted(buckets)
    rng.shuffle(keys)
    statuses = {r['task_id']:r['status'] for r in (diagnostics or {}).get('groups',[])}
    stratum_weights = [.25 if all(statuses.get(t['id'])=='all_correct' for t in buckets[k]) else 1.
                       for k in keys]
    batch = []
    for i in range(size):
        # First pass preserves coverage; remaining slots favor still-learning
        # strata. Uniformly downweighting every prompt in a mastered stratum
        # alone would leave that stratum's overall sampling frequency unchanged.
        key = keys[i] if i < len(keys) else rng.choices(keys,weights=stratum_weights)[0]
        pool = buckets[key]
        weights = [.25 if statuses.get(t['id'])=='all_correct' else 1. for t in pool]
        batch.append(rng.choices(pool, weights=weights)[0]['id'])
    return batch


def read(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def export(data, out, samples=None, group_size=8):
    tasks = read(Path(data)/'tasks.jsonl')
    out = Path(out)
    out.mkdir(parents=True,exist_ok=False)
    requests = [dict(task_id=t['id'],split=t['split'],task=t['task'],stage=t['stage'],
                     skill=t.get('category',t['skill']),request=request(t)) for t in tasks]
    (out/'requests.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in requests))
    diagnostics = group_diagnostics(tasks,read(samples) if samples else [],group_size=group_size)
    (out/'sampling_diagnostics.json').write_text(json.dumps(diagnostics,ensure_ascii=False,indent=2)+'\n')
    plan = dict(version=VERSION,eval_steps=10,group_size=group_size,parameters_updated=False,
        actual_LM=False,requests_sent=0,
        input_digest=digest(tasks),
        continuous_b_jobs=read(Path(data)/'sequences.jsonl'),
        stages={task:{str(stage):select_batch(tasks,task=task,stage=stage,size=32,seed=stage,
                                            diagnostics=diagnostics) for stage in range(3)} for task in ('B','P')},
        stage_advancement='Review per-skill sampling diagnostics before advancing; no automatic step-count progression.',
        sequences='Use sequences.jsonl and request(prior_turns=actual_prior_messages); never substitute gold. Stage-2 B sequences are separate jobs, not independent-checkpoint batches.')
    (out/'sampling_plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2)+'\n')
    return dict(requests=len(requests),requests_sent=0,actual_LM=False)


def probe_tasks(data, per_stratum=1):
    if type(per_stratum) is not int or per_stratum < 1:
        raise ValueError('Positive stratum size required')
    tasks=read(Path(data)/'tasks.jsonl')
    buckets=defaultdict(list)
    for t in tasks:
        if not t['teacher'].get('all_legal_accepted',False):
            buckets[(t['split'],t['task'],t['stage'],t.get('category',t['skill']))].append(t)
    selected=set()
    for pool in buckets.values():
        pool.sort(key=lambda t:(not t['teacher'].get('matched_result_use_certified',False),t['id']))
        selected.update(t['id'] for t in pool[:per_stratum])
    # Close over contrast partners; selection order must not drop paired items.
    pairs=read(Path(data)/'contrasts.jsonl')
    previous=None
    while previous != selected:
        previous=selected.copy()
        for pair in pairs:
            if selected.intersection(pair['members']):
                selected.update(pair['members'])
    return tasks,[t for t in tasks if t['id'] in selected]


def run_probe(data, out, *, model, base_url=None, base_urls=None, group_size=8, per_stratum=1, temperature=.8):
    """Explicit small inference probe, using the existing native HTTP client.

    No training, correctness feedback, or retries. Matched contrasts stay in the
    probe together. Each completion is independently sampled and accounted for.
    """
    from methods.vllm_client import OpenAICompatibleNegotiationClient
    if type(group_size) is not int or group_size < 2 or type(per_stratum) is not int or per_stratum < 1:
        raise ValueError('Positive stratum size and at least two group samples required')
    if bool(base_url)==bool(base_urls):
        raise ValueError('Specify exactly one base_url or a list of base_urls')
    endpoints=list(base_urls) if base_urls else [base_url]
    if any(not isinstance(u,str) or not u.strip() for u in endpoints) or len(set(endpoints))!=len(endpoints):
        raise ValueError('Nonempty distinct endpoints required')
    tasks,subset=probe_tasks(data,per_stratum)
    if not subset:
        raise ValueError('No probe tasks selected')
    out=Path(out)
    out.mkdir(parents=True,exist_ok=False)
    config=dict(version=VERSION,model=model,group_size=group_size,per_stratum=per_stratum,
        temperature=temperature,selected_task_ids=sorted(t['id'] for t in subset),input_digest=digest(tasks),
        parameters_updated=False,retries=0,planned_requests=len(subset)*group_size,
        worker_count=len(endpoints),assignment='One sequential group per endpoint worker; independent samples, no retries.',
        source_sha256={str(p):__import__('hashlib').sha256(p.read_bytes()).hexdigest() for p in
                       (Path(__file__),Path('training/b_sft/social_bp_curriculum.py'))})
    (out/'run_config.json').write_text(json.dumps(config,indent=2)+'\n')
    samples=[]
    queue=Queue()
    for t in subset:queue.put(t)
    lock=Lock()
    completed_groups=0
    with (out/'samples.jsonl').open('w') as f:
        def worker(worker_id, endpoint):
            nonlocal completed_groups
            client=OpenAICompatibleNegotiationClient(endpoint,model,
                api_key=os.environ.get('BENAC_P_VLLM_API_KEY','EMPTY'),temperature=temperature,
                timeout=120,max_tokens=1024)
            while True:
                try:t=queue.get_nowait()
                except Empty:return
                payload=request(t)
                for i in range(group_size):
                    row=dict(task_id=t['id'],sample_index=i,worker_id=worker_id)
                    try:
                        response=client.complete_with_tools(**payload)
                        row.update(raw_message=dict(response.raw_message),finish_reason=response.finish_reason,
                                   usage=dict(response.usage),status='completed')
                    except Exception as exc:
                        row.update(status='infrastructure_failure',error_type=type(exc).__name__)
                    with lock:
                        samples.append(row)
                        f.write(json.dumps(row,ensure_ascii=False)+'\n');f.flush()
                with lock:
                    completed_groups+=1
                    diagnostics=group_diagnostics(subset,samples,group_size=group_size)
                    (out/'sampling_diagnostics.json').write_text(json.dumps(diagnostics,ensure_ascii=False,indent=2)+'\n')
                    print(json.dumps(dict(task=t['id'],completed_groups=completed_groups,
                                         total_groups=len(subset))),flush=True)
        with ThreadPoolExecutor(max_workers=len(endpoints)) as pool:
            futures=[pool.submit(worker,i,endpoint) for i,endpoint in enumerate(endpoints)]
            for future in futures:future.result()
    diagnostics=group_diagnostics(subset,samples,group_size=group_size)
    diagnostics.update(requests_sent=len(samples),model_sampling_provenance_verified=True,
                       actual_LM=any(s['status']=='completed' for s in samples),parameters_updated=False)
    (out/'sampling_diagnostics.json').write_text(json.dumps(diagnostics,ensure_ascii=False,indent=2)+'\n')
    return dict(requests_sent=len(samples),actual_LM=diagnostics['actual_LM'],parameters_updated=False)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data',required=True)
    p.add_argument('--out',required=True)
    p.add_argument('--samples')
    p.add_argument('--group-size',type=int,default=8)
    endpoints=p.add_mutually_exclusive_group()
    endpoints.add_argument('--base-url',help='Explicitly run inference instead of exporting requests')
    endpoints.add_argument('--base-urls',nargs='+',help='One worker per verified model endpoint')
    p.add_argument('--model')
    p.add_argument('--per-stratum',type=int,default=1)
    a=p.parse_args()
    if bool(a.base_url or a.base_urls) != bool(a.model) or (a.base_url or a.base_urls) and a.samples:
        p.error('Use base-url and model together; do not combine live inference with samples')
    print(json.dumps(run_probe(a.data,a.out,base_url=a.base_url,base_urls=a.base_urls,model=a.model,
        group_size=a.group_size,per_stratum=a.per_stratum) if a.base_url or a.base_urls else
        export(a.data,a.out,a.samples,a.group_size)))
