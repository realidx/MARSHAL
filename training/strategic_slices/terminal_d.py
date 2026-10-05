"""Eight independent model rollouts per frozen terminal candidate; no training.

Environment truth and oracle scores remain in local evidence, never in requests.
Interrupted runs resume at atomic parent records; HTTP failures abort the run.
"""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import shutil
import threading
import time
from urllib.request import Request, urlopen

import numpy as np

from .common import decode, digest, file_hash, materialize_node, request, seed_for, stable, write_json, write_rows
from .freeze import atomic_json, source_identity
from .terminal_candidates import TerminalCandidates, sample_member_world

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT/'examples/strategic_slices/terminal_d_soc.json'


def load_config(path=DEFAULT_CONFIG):
    cfg = json.loads(Path(path).read_text())
    if cfg['replicas'] != 8 or cfg['temperature'] <= 0:
        raise ValueError('This protocol requires eight stochastic samples per slice')
    if cfg['workers'] < 1 or cfg['context'] <= cfg['max_tokens'] or cfg['max_tokens'] < 1:
        raise ValueError('Invalid serving limits')
    if not (0 < cfg['top_p'] <= 1 and 0 < cfg['gpu_memory_utilization'] <= 1):
        raise ValueError('Invalid sampling/memory settings')
    if cfg['tensor_parallel_size'] != 1 or cfg['tool_call_parser'] != 'hermes':
        raise ValueError('Expected the single-GPU Hermes serving profile')
    return cfg


def load_dataset(path):
    dataset = TerminalCandidates(path)
    marker = json.loads((dataset.root/'CANDIDATES_VERIFIED.json').read_text())
    if marker['manifest_sha256'] != file_hash(dataset.root/'manifest.json'):
        raise ValueError('Unverified candidate manifest')
    counts = Counter(r['parent_id'] for r in dataset.candidates)
    if len(dataset.parents) != 100 or len(dataset.candidates) != 800 or set(counts.values()) != {8}:
        raise ValueError('Expected frozen 100-parent, 800-candidate balanced pool')
    return dataset


class TerminalRollout:
    def __init__(self, tree, row, replica, seed):
        self.tree, self.row, self.replica = tree, row, replica
        self.seed = seed_for(seed, 'terminal-D', row['id'], replica)
        self.member_index, self.world_index = sample_member_world(row, np.random.default_rng(seed_for(self.seed, 'reset')))
        self.member = row['members'][self.member_index]
        self.world = tree.worlds[self.world_index]
        self.index = self.member['root_index']
        self.node = materialize_node(tree, self.index, self.world)
        self.ego = row['ego']
        if tree.entries[self.index].actor != self.ego:
            raise ValueError('Entrance actor mismatch')
        self.rng = np.random.default_rng(seed_for(self.seed, 'oracle-actions'))
        self.controlled = 0
        self.status, self.utility = 'running', None
        self.calls, self.steps = [], []

    def request(self, cfg):
        req = request(self.tree.rules, self.node, self.world,
                      seed_for(self.seed, 'model', self.controlled), cfg['temperature'])
        visible = json.loads(req['messages'][1]['content'])
        visible['evaluation_window'] = dict(
            remaining_controlled_decisions=self.row['k']-self.controlled,
            objective='Your terminal utility in the original game',
            continuation='Other players and you after this window follow the fixed reference policy. '
                         'Both proposals and responses count as your decisions.')
        req['messages'][1]['content'] = stable(visible)
        req.update(max_tokens=cfg['max_tokens'], top_p=cfg['top_p'], top_k=cfg['top_k'],
                   repetition_penalty=cfg['repetition_penalty'], tool_choice='auto', parallel_tool_calls=False)
        return req

    def step(self, ai, source):
        entry = self.tree.entries[self.index]
        actions = self.tree.rules.actions(self.node)
        if stable([a.to_dict() for a in actions]) != stable([a.to_dict() for a in entry.actions]):
            raise ValueError('Live actions differ from saved native tree')
        self.steps.append(dict(node=self.index, actor=entry.actor, action_index=ai, source=source))
        self.node = self.tree.rules.step(self.node, actions[ai], realized_world=self.world)
        self.index = entry.children[ai]
        if self.node.state.public_state() != self.tree.entries[self.index].node.state.public_state():
            raise ValueError('Live state diverged from saved native tree')

    def advance(self):
        while self.status == 'running':
            if self.node.state.is_terminal:
                self.utility = list(self.tree.rules.terminal_payoffs(self.node, self.world))
                self.status = 'terminal'
                return
            entry = self.tree.entries[self.index]
            if entry.actor == self.ego and self.controlled < self.row['k']:
                return
            ai = int(self.rng.choice(len(entry.actions), p=self.tree.policy[self.index][:, self.world_index]))
            self.step(ai, 'saved-reference')

    def accept(self, output, req):
        if output['completion'].get('status') == 'infrastructure_failure':
            raise RuntimeError('Infrastructure failure is not a model reward')
        ai, status = decode(output, self.tree.rules.actions(self.node))
        prompt_hash = digest({k: req[k] for k in ('messages', 'tools')})
        root_gap = None
        if not self.calls and status == 'ok':
            root_gap = self.member['V_star'] - self.member['root_Q'][ai]
            if root_gap < -1e-7:
                raise ValueError('Root action exceeds saved best value')
        self.calls.append(dict(output, request=req, node=self.index, action_index=ai,
                               protocol_status=status, prompt_sha256=prompt_hash,
                               first_action_oracle_gap=root_gap))
        if status != 'ok':
            self.status = status
            return
        self.controlled += 1
        self.step(ai, 'model')
        self.advance()

    def record(self):
        own = self.world[self.ego]
        return dict(slice_id=self.row['id'], parent_id=self.row['parent_id'], replica=self.replica,
                    seed=self.seed, member_index=self.member_index, world_index=self.world_index,
                    status=self.status, controlled_decisions=self.controlled,
                    utility=self.utility[self.ego] if self.utility is not None else None,
                    terminal_utilities=self.utility, utility_bounds=[sum(min(0, v) for v in own), sum(max(0, v) for v in own)],
                    steps=self.steps, calls=self.calls)


class HTTPGenerator:
    def __init__(self, url, model, cfg, tokenizer, evidence):
        self.url, self.model, self.cfg, self.tokenizer = url.rstrip('/'), model, cfg, tokenizer
        self.evidence = Path(evidence)
        self.lock = threading.Lock()

    def log(self, row):
        with self.lock, self.evidence.open('a') as handle:
            handle.write(stable(row)+'\n')

    def __call__(self, requests):
        # Tokenize serially before HTTP dispatch: check every dynamic prompt,
        # including response nodes and private investigation answers.
        lengths = []
        for req in requests:
            encoded = self.tokenizer.apply_chat_template(req['messages'], tools=req['tools'],
                tokenize=True, add_generation_prompt=True, return_dict=True, truncation=False)
            ids = encoded['input_ids']
            if not isinstance(ids, list) or not ids or not all(type(i) is int for i in ids):
                raise ValueError('Expected flat token IDs')
            lengths.append(len(ids))
            if len(ids)+req['max_tokens'] > self.cfg['context']:
                raise ValueError('Prompt exceeds context; truncation is forbidden')

        def complete(item):
            req, length = item
            body = dict(req, model=self.model)
            started = time.monotonic()
            try:
                wire = Request(self.url+'/chat/completions', data=json.dumps(body).encode(),
                               headers={'Content-Type': 'application/json'})
                with urlopen(wire, timeout=self.cfg['http_timeout_seconds']) as response:
                    result = json.load(response)
                if len(result.get('choices', [])) != 1:
                    raise ValueError('Expected exactly one completion')
                choice = result['choices'][0]
                if not isinstance(choice.get('message'), dict) or 'finish_reason' not in choice:
                    raise ValueError('Malformed completion envelope')
                usage = result.get('usage')
                if not usage or usage['prompt_tokens'] != length:
                    raise ValueError('Server/tokenizer prompt token mismatch')
                if type(usage.get('completion_tokens')) is not int or not 0 <= usage['completion_tokens'] <= req['max_tokens']:
                    raise ValueError('Invalid completion token count')
                self.log(dict(status='ok', request=body, response=result, prompt_tokens=length))
                return dict(completion=dict(finish_reason=choice['finish_reason'], raw_message=choice['message']),
                            usage=usage, elapsed_seconds=time.monotonic()-started)
            except Exception as exc:
                self.log(dict(status='infrastructure_failure', request=body, error=repr(exc)))
                raise
        with ThreadPoolExecutor(max_workers=self.cfg['workers']) as pool:
            return list(pool.map(complete, zip(requests, lengths)))


def mock_generate(requests):
    """Seeded legal random actor, explicitly not base-model evidence."""
    result = []
    for req in requests:
        choices = req['tools'][0]['function']['parameters']['properties']['action_index']['enum']
        ai = int(np.random.default_rng(req['seed']).choice(choices))
        result.append(dict(completion=dict(finish_reason='tool_calls', raw_message=dict(tool_calls=[
            dict(function=dict(name='act', arguments=json.dumps(dict(action_index=ai))))]))))
    return result


def mean_interval(values, seed):
    if not values:
        return dict(mean=None, standard_error=None, bootstrap95=None, n=0)
    values = np.asarray(values, dtype=float)
    samples = np.random.default_rng(seed).choice(values, size=(2000, len(values))).mean(axis=1)
    return dict(mean=float(values.mean()), n=len(values),
                standard_error=float(values.std(ddof=1)/np.sqrt(len(values))) if len(values)>1 else None,
                bootstrap95=np.quantile(samples, [.025, .975]).tolist())


def summarize_slice(row, games, seed):
    complete = [g for g in games if g['status'] == 'terminal']
    utilities = [g['utility'] for g in complete]
    estimate = mean_interval([row['V_star']-u for u in utilities], seed_for(seed, row['id']))
    full = len(complete) == len(games)
    lower_u = np.mean([g['utility'] if g['utility'] is not None else g['utility_bounds'][0] for g in games])
    upper_u = np.mean([g['utility'] if g['utility'] is not None else g['utility_bounds'][1] for g in games])
    prompts = defaultdict(list)
    for game in games:
        if game['calls']:
            call = game['calls'][0]
            if call['first_action_oracle_gap'] is not None:
                prompts[call['prompt_sha256']].append(call)
    groups = []
    for prompt, calls in prompts.items():
        gaps = [c['first_action_oracle_gap'] for c in calls]
        groups.append(dict(prompt_sha256=prompt, n=len(calls),
            distinct_actions=len({c['action_index'] for c in calls}),
            oracle_gap_span=max(gaps)-min(gaps),
            mixed_optimal_suboptimal=min(gaps)<=1e-7 and max(gaps)>1e-7))
    return dict(slice_id=row['id'], parent_id=row['parent_id'], split=row['split'], k=row['k'], ego=row['ego'],
        decision_kind=row['decision_kind'], C=row['C_span'], information_channels=row['information_channels'],
        V_star=row['V_star'], replicas=len(games), completed=len(complete),
        statuses=dict(Counter(g['status'] for g in games)),
        D=estimate['mean'] if full else None, D_over_C=estimate['mean']/row['C_span'] if full else None,
        D_completed_only=estimate, D_missing_outcome_bounds=[row['V_star']-upper_u, row['V_star']-lower_u],
        reward_std_completed=float(np.std(utilities)) if utilities else None,
        reward_span_completed=float(np.ptp(utilities)) if utilities else None,
        sampled_reward_contrast=bool(full and np.ptp(utilities)>1e-7),
        first_decision_groups=groups,
        root_value_contrast=any(g['oracle_gap_span']>1e-7 for g in groups),
        root_mixed_optimal_suboptimal=any(g['mixed_optimal_suboptimal'] for g in groups),
        distinct_model_trajectories=len({tuple((c['prompt_sha256'], c['action_index']) for c in g['calls']) for g in games}))


def run_evaluation(dataset, cfg, output, generate, identity, *, parent_limit=None, resume=False):
    output = Path(output)
    parent_ids = sorted(dataset.parents)[:parent_limit]
    protocol = dict(version='terminal-D-eight-independent-v1', dataset_sha256=file_hash(dataset.root/'manifest.json'),
        config=cfg, model_identity=identity, parent_ids=parent_ids, source_identity=source_identity(),
        reset='Independent joint entrance/world draw per replica; independent model and oracle RNG streams.',
        D='V_star minus mean native-terminal utility; no clipping; primary D null on incomplete samples.',
        selection='No final selection. Held-out metrics are diagnostic only; training shortlist must use train.',
        signal='Reward variation includes environment noise. Root-Q contrast uses identical visible prompts, '
               'optimal continuation within remaining window, and is not full-trajectory success or proof of learnability.')
    if output.exists():
        if not resume:
            raise FileExistsError('Use a fresh output directory or explicit resume')
        if json.loads((output/'protocol.json').read_text()) != protocol:
            raise ValueError('Resume protocol/model/data/source mismatch')
    else:
        output.mkdir(parents=True)
        write_json(output/'protocol.json', protocol)
        (output/'parents').mkdir()
        for name in protocol['source_identity']:
            target = output/'source'/name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT/name, target)
    for name, checksum in protocol['source_identity'].items():
        if file_hash(output/'source'/name) != checksum:
            raise ValueError('Saved source snapshot mismatch')
    all_results = []
    try:
        for number, pid in enumerate(parent_ids):
            rows = sorted((r for r in dataset.candidates if r['parent_id']==pid), key=lambda r:r['id'])
            path = output/'parents'/f'{pid}.json'
            if path.exists():
                saved = json.loads(path.read_text())
                if saved['sha256'] != digest(saved['result']):
                    raise ValueError('Saved parent result changed')
                result = saved['result']
                if result['protocol_sha256'] != digest(protocol) or result['parent_id'] != pid:
                    raise ValueError('Saved parent protocol mismatch')
            else:
                tree = dataset.reference(rows[0])
                jobs = [TerminalRollout(tree, row, replica, cfg['seed']) for row in rows for replica in range(cfg['replicas'])]
                while any(j.status == 'running' for j in jobs):
                    active = [j for j in jobs if j.status == 'running']
                    for offset in range(0, len(active), cfg['workers']):
                        batch = active[offset:offset+cfg['workers']]
                        requests = [j.request(cfg) for j in batch]
                        answers = generate(requests)
                        if len(answers) != len(batch):
                            raise ValueError('Missing generation results')
                        for job, req, answer in zip(batch, requests, answers):
                            job.accept(answer, req)
                games = [j.record() for j in jobs]
                slices = [summarize_slice(row, [g for g in games if g['slice_id']==row['id']], cfg['seed']) for row in rows]
                result = dict(parent_id=pid, protocol_sha256=digest(protocol), games=games, slices=slices)
                atomic_json(path, dict(sha256=digest(result), result=result))
            expected = {(r['id'], i) for r in rows for i in range(cfg['replicas'])}
            if {(g['slice_id'], g['replica']) for g in result['games']} != expected or len(result['games']) != len(expected):
                raise ValueError('Missing or repeated slice replicas')
            all_results.append(result)
            print(f'parents {number+1}/{len(parent_ids)}: {pid}', flush=True)
        rows = [row for result in all_results for row in result['slices']]
        games = [game for result in all_results for game in result['games']]
        summaries = {}
        for split in ('train', 'validation', 'test'):
            cohort = [r for r in rows if r['split']==split]
            summaries[split] = dict(slices=len(cohort), complete_slices=sum(r['D'] is not None for r in cohort),
                mean_D_complete_slices=float(np.mean([r['D'] for r in cohort if r['D'] is not None])) if any(r['D'] is not None for r in cohort) else None,
                sampled_reward_contrast_slices=sum(r['sampled_reward_contrast'] for r in cohort),
                root_value_contrast_slices=sum(r['root_value_contrast'] for r in cohort),
                root_mixed_optimal_suboptimal_slices=sum(r['root_mixed_optimal_suboptimal'] for r in cohort),
                complete_root_value_contrast_slices=sum(r['D'] is not None and r['root_value_contrast'] for r in cohort))
        strata = []
        for field in ('k', 'decision_kind', 'players'):
            grouped = defaultdict(list)
            for row in rows:
                label = dataset.parents[row['parent_id']].get('players') if field=='players' else row[field]
                grouped[(row['split'], str(label))].append(row)
            for (split,label), cohort in sorted(grouped.items()):
                completed = [r['D'] for r in cohort if r['D'] is not None]
                strata.append(dict(split=split, dimension=field, value=label, slices=len(cohort),
                    complete_slices=len(completed), mean_D_complete_slices=float(np.mean(completed)) if completed else None,
                    root_value_contrast_slices=sum(r['root_value_contrast'] for r in cohort)))
        calls = [c for g in games for c in g['calls']]
        summary = dict(mock=identity['mock'], actual_model_actions=not identity['mock'],
            model_learning_validated=False, final_100_selected=False, parents=len(parent_ids), slices=len(rows),
            trajectories=len(games), completed=sum(g['status']=='terminal' for g in games),
            decision_calls=len(calls), statuses=dict(Counter(g['status'] for g in games)),
            response_tokens=sum((c.get('usage') or {}).get('completion_tokens', 0) for c in calls) if not identity['mock'] else None,
            call_statuses=dict(Counter(c['protocol_status'] for c in calls)), splits=summaries, strata=strata,
            train_at_least_100_complete_root_value_contrast_slices=summaries['train']['complete_root_value_contrast_slices']>=100,
            interpretation=protocol['signal'], uncertainty='Eight samples give coarse estimates; bootstrap intervals are descriptive. Missing-outcome bounds are not confidence intervals.')
        if source_identity() != protocol['source_identity']:
            raise ValueError('Source changed during evaluation')
        write_rows(output/'slices.jsonl', rows)
        write_rows(output/'train_signal_candidates.jsonl', [r for r in rows if r['split']=='train' and r['D'] is not None and r['root_value_contrast']])
        write_json(output/'summary.json', summary)
        (output/'REPORT.md').write_text('# Terminal slice D and signal diagnostic\n\n'+
            ('**MOCK: no model was evaluated.**\n\n' if identity['mock'] else '')+
            f"{len(rows)} slices; {len(games)} trajectories; {summary['completed']} completed.\n\n"+
            '| Split | Slices | Complete slices | Reward contrast | Root value contrast | Mixed optimal/suboptimal root |\n'+
            '| --- | --- | --- | --- | --- | --- |\n'+''.join(
                f"| {s} | {v['slices']} | {v['complete_slices']} | {v['sampled_reward_contrast_slices']} | {v['root_value_contrast_slices']} | {v['root_mixed_optimal_suboptimal_slices']} |\n" for s,v in summaries.items())+
            '\n'+protocol['signal']+'\n\nNo training or final 100-slice selection. Per-slice D, uncertainty, failures and signal diagnostics are in `slices.jsonl`.\n')
        proof = {str(p.relative_to(output)):file_hash(p) for p in [output/'protocol.json', output/'summary.json', output/'slices.jsonl', output/'train_signal_candidates.jsonl', output/'REPORT.md', *sorted((output/'parents').glob('*.json'))]}
        atomic_json(output/'COMPLETE.json', dict(files=proof, mock=identity['mock']))
        if (output/'FAILED.json').exists():
            (output/'FAILED.json').replace(output/'RECOVERED_FAILURE.json')
        return summary
    except BaseException as exc:
        atomic_json(output/'FAILED.json', dict(error=repr(exc), completed_parent_records=len(all_results),
            recovery='Explicit resume reuses completed parents and repeats only the unfinished parent. No automatic answer retries.'))
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=DEFAULT_CONFIG)
    parser.add_argument('--data', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--mock', action='store_true')
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--limit-parents', type=int)
    args = parser.parse_args()
    cfg = load_config(args.config)
    dataset = load_dataset(args.data or ROOT/cfg['data'])
    if args.check:
        print(stable(dict(parents=100, slices=800, trajectories=6400,
                         max_model_calls=sum(r['k']*8 for r in dataset.candidates),
                         dataset_sha256=file_hash(dataset.root/'manifest.json'), gpu_started=False)))
        return
    if not args.mock or args.output is None:
        parser.error('Local entry supports --check or --mock --output; actual model run uses run_terminal_d.py inside an allocation')
    if args.limit_parents is not None and args.limit_parents < 1:
        parser.error('--limit-parents must be positive')
    run_evaluation(dataset, cfg, args.output, mock_generate, dict(mock=True, model=None),
                   parent_limit=args.limit_parents, resume=args.resume)


if __name__ == '__main__':
    main()
