"""Build linked answer-only B/P development data with replayed branch labels.

Reference scope: conditional native binary endgames, one hidden preference,
declared RationalPartner model. This does not relabel the old MCTS corpus.
"""
import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
from training.social_mixed.frozen.benac_p.endgame_diagnose import Fixture, Suite, decode_action
from training.social_mixed.frozen.benac_p.endgame_mine import candidates
from training.social_mixed.frozen.benac_p.functional_dependency import certify
from training.social_mixed.frozen.benac_p.endgame import SearchLimit
from training.social_mixed.frozen.benac_p.endgame_partner import InformationStateRequired
from training.social_mixed.frozen.benac_p.diagnose_protocol import submission_tool

VERSION = 'decision-corpus-v1'
SYSTEM = '''You control only the named ego player. Use the public game rules, your own preferences, the declared partner behavior model and the visible history. Other players' candidate preferences are hypotheses, not revealed realized types. For B, return all and only evidence-supported preferences of the queried partner. Your actions change the state and the evidence you can obtain; they do not reveal other players' private preferences by themselves. For P, use the supplied evidence-supported partner judgment and history to select a legal action with maximum expected terminal utility under the declared reference model. More informative actions are not automatically better: account for their costs and subsequent decisions. Submit exactly one requested tool call. Do not output reasoning, probabilities, utilities or Q values.'''
CATEGORIES = ('formation', 'maintain', 'update', 'belief_sensitive_planning',
              'own_goal_change', 'planning_under_uncertainty',
              'action_changes_information', 'post_evidence_planning')


def digest(x):
    return hashlib.sha256(json.dumps(x, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def partition(n_players, source_id, status):
    if status == 'development':
        return 'development'
    if n_players == 5:
        return 'ood_test'
    bucket = int(digest(source_id)[:8], 16) % 100
    return 'train' if bucket < 70 else 'validation' if bucket < 85 else 'test'


def export_fixture(raw, max_nodes, max_arms, status):
    if any(not g.get('binary', True) for g in raw['game']['goals']):
        raise ValueError('This reference renderer only supports binary goals; refusing silent conversion.')
    if len(raw['query'].get('goals', [raw['query'].get('goal')])) != 1:
        raise ValueError('v1 supports one queried preference, not lossy marginalization.')
    f = Fixture(raw, max_nodes)
    proof = certify(f)
    suite = Suite([f])
    root_id = f.id + '/root'
    suite.add_case(f, f.root, root_id)
    q = suite.cases[root_id]['q']
    best = max(v for _, v in q)
    chosen = [('reference_best', next(a for a, v in q if best-v < 1e-9))]
    if proof.get('planning_to_belief'):
        for key in ('low', 'high'):
            chosen.append((key + '_information', decode_action(proof['planning_to_belief'][key]['action'])))
    chosen.append(('value_contrast', min(q, key=lambda av: av[1])[0]))
    seen = set()
    for name, action in chosen:
        key = digest(action.to_dict())
        if key in seen:
            continue
        if len(seen) >= max_arms:
            break
        seen.add(key)
        suite.add_arm(f, name, action)
    # Game identity ignores query, role and sampled private preferences, so all
    # related decision points/branches stay together. Generated n=5 is OOD only.
    public_game = deepcopy(raw['game'])
    for key in ('seed', 'metadata', 'private_preferences'):
        public_game.pop(key, None)
    source_id = 'game-' + digest(public_game)[:24]
    split = partition(f.spec.n_players, source_id, status)
    records, labels, links = [], [], []
    for task in suite.tasks:
        if task['id'].endswith('/plan_model'):
            continue  # identical teacher-forced payload, not an independent item
        is_b = task['kind'] == 'semantic_belief'
        gold = suite.labels[task['id']]
        tool = submission_tool(task)
        if is_b:
            answer = {'possible_preferences': gold['support']}
        else:
            # One reproducible demonstration; every tied optimum remains correct
            # in the gold sidecar. Avoid always choosing the smallest action id.
            optimum = gold['optimal_indices']
            answer = {'action_index': optimum[int(digest(task['id'])[:8], 16) % len(optimum)]}
        payload = deepcopy(task['input'])
        category = []
        if is_b and gold['case'] == root_id:
            category.append('formation')
        if not is_b and len(gold['support']) > 1:
            category.append('planning_under_uncertainty')
        if not is_b and gold['case'] != root_id:
            category.append('post_evidence_planning')
        if not is_b and gold['case'] == root_id and proof.get('belief_to_planning'):
            category.append('belief_sensitive_planning')
        record = dict(id=task['id'], source_id=source_id, decision_id=gold['case'],
                      root_decision_id=root_id, split=split, task='B' if is_b else 'P',
                      categories=category, supervision='assistant_tool_call_only',
                      reasoning_supervision=False, allow_reasoning=False,
                      messages=[{'role': 'system', 'content': SYSTEM},
                                {'role': 'user', 'content': json.dumps(payload, separators=(',', ':'))},
                                {'role': 'assistant', 'content': '', 'tool_calls': [
                                    {'id': 'call_answer', 'type': 'function', 'function': {
                                        'name': tool['function']['name'], 'arguments': json.dumps(answer, separators=(',', ':'))}}]}],
                      tools=[tool])
        records.append(record)
        labels.append(dict(id=task['id'], source_id=source_id, split=split, task=record['task'],
                           possible_preferences=gold['support'], action_values=gold['q'],
                           optimal_action_indices=gold['optimal_indices']))
    lookup = {r['id']: r for r in records}
    root_support = f.support(f.root)
    for arm_name, arm in suite.arms.get(f.id, {}).items():
        action_index = next(i for i, (a, _) in enumerate(q) if a.to_dict() == arm['action'])
        for branch in arm['branches']:
            after = branch['case']
            child = suite.cases[after]['node']
            kind = 'maintain' if branch['support'] == root_support else 'update'
            assert set(branch['support']) <= set(root_support)
            b_id, p_id = after+'/belief', after+'/plan_oracle'
            lookup[b_id]['categories'] = sorted(set(lookup[b_id]['categories'] + [kind]))
            links.append(dict(id=digest([root_id, action_index, after]), source_id=source_id, split=split,
                              root_decision_id=root_id, before_B=root_id+'/belief', before_P=root_id+'/plan_oracle',
                              after_B=b_id, after_P=p_id if p_id in lookup else None,
                              branch_action=arm['action'], branch_action_index=action_index,
                              branch_is_root_optimal=action_index in suite.labels[root_id+'/belief']['optimal_indices'],
                              arm=arm_name, relation=kind, evidence=branch['evidence'],
                              reference_branch_weight=branch['weight'], terminal=child.state.is_terminal,
                              before_support=root_support, after_support=branch['support']))
    return records, labels, links, dict(root_decision_id=root_id, source_id=source_id, split=split,
                                      proof=proof, fixture=raw)


def validate(records, gold, links):
    by_id = {r['id']: r for r in records}
    if len(by_id) != len(records) or len(gold) != len(records) or {g['id'] for g in gold} != set(by_id):
        raise ValueError('Duplicate ids or gold mismatch')
    source_splits = {}
    for r, g in zip(records, gold):
        if r['id'] != g['id']:
            raise ValueError('Gold order mismatch')
        old = source_splits.setdefault(r['source_id'], r['split'])
        if old != r['split']:
            raise ValueError('Source leakage across splits')
        payload = json.loads(r['messages'][1]['content'])
        if any(k in payload for k in ('q', 'action_values', 'optimal_indices', 'support', 'proof')):
            raise ValueError('Teacher-only label in student payload')
        answer = json.loads(r['messages'][2]['tool_calls'][0]['function']['arguments'])
        if r['task'] == 'B':
            if 'partner_judgment' in payload or answer['possible_preferences'] != g['possible_preferences']:
                raise ValueError('B target leakage or incorrect target')
        else:
            if answer['action_index'] not in g['optimal_action_indices']:
                raise ValueError('Nonoptimal P demonstration')
            if payload['partner_judgment']['possible_preferences'] != g['possible_preferences']:
                raise ValueError('P received a hindsight or inconsistent judgment')
            actions = payload['legal_actions']
            if [a['action_index'] for a in actions] != list(range(len(g['action_values']))):
                raise ValueError('Action table is misaligned with values')
    for link in links:
        for key in ('before_B', 'before_P', 'after_B', 'after_P'):
            if link[key] is not None and (link[key] not in by_id or by_id[link[key]]['split'] != link['split']
                                         or by_id[link[key]]['source_id'] != link['source_id']):
                raise ValueError('Broken/cross-split branch link')
        if not set(link['after_support']) <= set(link['before_support']):
            raise ValueError('Evidence added a previously excluded possibility')
        if link['relation'] != ('maintain' if link['before_support'] == link['after_support'] else 'update'):
            raise ValueError('Incorrect update tag')


def write_bundle(out, records, gold, links, certificates, attempts, args):
    validate(records, gold, links)
    def save(name, data):
        (out/name).write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n')
    def jsonl(name, rows):
        (out/name).write_text(''.join(json.dumps(r, ensure_ascii=False)+'\n' for r in rows))
    for split in sorted({r['split'] for r in records}):
        rows = [r for r in records if r['split'] == split]
        jsonl(split+'.jsonl', rows)
        jsonl(split+'_prompts.jsonl', [dict(id=r['id'], source_id=r['source_id'], task=r['task'],
              messages=r['messages'][:-1], tools=r['tools']) for r in rows])
        jsonl(split+'_gold.jsonl', [g for g in gold if g['split'] == split])
        jsonl(split+'_links.jsonl', [l for l in links if l['split'] == split])
        for task in ('B', 'P'):
            jsonl(split+'_'+task+'.jsonl', [r for r in rows if r['task'] == task])
    jsonl('certificates.jsonl', certificates)
    jsonl('attempts.jsonl', attempts)
    categories = Counter(c for r in records for c in r['categories'])
    information = sum(bool(c['proof'].get('planning_to_belief')) for c in certificates)
    categories['action_changes_information'] = information
    summary = dict(records=len(records), sources=len({r['source_id'] for r in records}),
                   decisions=len({r['decision_id'] for r in records}), branches=len(links),
                   tasks=dict(Counter(r['task'] for r in records)),
                   splits={s: dict(records=sum(r['split']==s for r in records),
                            sources=len({r['source_id'] for r in records if r['split']==s})) for s in sorted({r['split'] for r in records})},
                   coverage={k: categories[k] for k in CATEGORIES},
                   coverage_units='Task rows, except action_changes_information counts root certificates; categories overlap.',
                   missing_categories=[k for k in CATEGORIES if not categories[k]],
                   exclusions=sum(a.get('status') == 'excluded' for a in attempts),
                   formal_training_ready=False)
    save('summary.json', summary)
    save('manifest.json', dict(version=VERSION, arguments=vars(args),
         scope='Answer-only, linked B/P conditional binary endgames under declared exact reference partner policy. Not general unknown-policy social reasoning.',
         caveats=['P uses reference B during SFT; generated-B robustness is not established.',
                  'Certificates use teacher values, never student answers. B->P does not require a mandatory action switch.',
                  'Information gap is not positive information-mediated utility; post-evidence P is not proof of beneficial information.',
                  'Only one partner-goal entry is unknown; other entries are supplied.',
                  'Own-goal counterfactuals and policy-family robustness are not implemented.',
                  'The 220-game finite-MCTS corpus is not relabeled by this different reference.',
                  'Groups share games and are not independent replications. P ties are all valid in gold.',
                  'Mixed B/P is not supported by the existing B-only train.py; no training launched.']))
    save('checksums.json', {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.iterdir()) if p.is_file() and p.name not in ('checksums.json','READY.json')})
    save('READY.json', dict(complete=True, records=len(records), validated=True,
                           checksums_sha256=hashlib.sha256((out/'checksums.json').read_bytes()).hexdigest()))
    return summary


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output-dir', required=True)
    p.add_argument('--fixtures', help='Existing fixtures JSON, always marked development; never recycled as held-out test.')
    p.add_argument('--players', type=int, nargs='+', choices=(3,4,5), default=[3,4])
    p.add_argument('--seed', type=int, default=910000)
    p.add_argument('--seeds-per-player', type=int, default=4)
    p.add_argument('--actions-per-player', type=int, default=2)
    p.add_argument('--goals', type=int, default=7)
    p.add_argument('--rounds', type=int, default=2)
    p.add_argument('--max-remaining-turns', type=int, default=3)
    p.add_argument('--max-nodes', type=int, default=3000)
    p.add_argument('--max-fixtures-per-seed', type=int, default=2)
    p.add_argument('--max-arms', type=int, default=4)
    args = p.parse_args(argv)
    if min(args.seeds_per_player,args.max_nodes,args.max_fixtures_per_seed,args.max_remaining_turns) < 1 or args.max_arms < 3:
        p.error('Budgets must be positive; max-arms must be >=3 to retain both information arms.')
    out = Path(args.output_dir)
    if out.exists():
        p.error('Output exists; use a new path to preserve the existing corpus.')
    out.mkdir(parents=True)
    records, gold, links, certificates, attempts = [], [], [], [], []
    processed = set()
    def accept(raw, status):
        if raw['id'] in processed:
            return False
        start = time.monotonic()
        try:
            r,g,l,c = export_fixture(raw,args.max_nodes,args.max_arms,status)
        except (SearchLimit, InformationStateRequired) as exc:
            attempts.append(dict(id=raw['id'],status='excluded',reason=str(exc)))
            return False
        records.extend(r);gold.extend(g);links.extend(l);certificates.append(c)
        processed.add(raw['id'])
        attempts.append(dict(id=raw['id'],status='accepted',seconds=round(time.monotonic()-start,3)))
        print(json.dumps(dict(id=raw['id'],records=len(r),branches=len(l),groups=c['proof']['groups'])),flush=True)
        return True
    if args.fixtures:
        raw = json.loads(Path(args.fixtures).read_text())
        for f in (raw['fixtures'] if isinstance(raw,dict) else raw):
            accept(f,'development')
    else:
        for players in sorted(set(args.players)):
            for seed in range(args.seed,args.seed+args.seeds_per_player):
                count = 0
                # n-dependent source seeds avoid fixture-id collisions.
                actual_seed = seed + (players-3)*1000000
                for raw in candidates(actual_seed,args.max_nodes,args.actions_per_player,args.goals,
                                      args.rounds,1,lambda e: attempts.append(dict(e,status='excluded')),
                                      args.max_remaining_turns,2,n_players=players):
                    if accept(raw,'generated'):
                        count += 1
                    if count >= args.max_fixtures_per_seed:
                        break
                print(json.dumps(dict(seed=actual_seed,players=players,accepted=count)),flush=True)
                attempts.append(dict(status='seed_summary',seed=actual_seed,players=players,accepted=count))
    if not records:
        (out/'attempts.json').write_text(json.dumps(attempts,indent=2))
        raise SystemExit('No valid decisions within budget; no READY marker written.')
    print(json.dumps(write_bundle(out,records,gold,links,certificates,attempts,args),indent=2))


if __name__ == '__main__':
    main()
