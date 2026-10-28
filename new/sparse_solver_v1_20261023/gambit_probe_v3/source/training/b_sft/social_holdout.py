"""Frozen, model-blind development generalization recipes and online audits."""
from copy import deepcopy
from itertools import permutations, product
from pathlib import Path
import hashlib
import json
import random

from training.b_sft.coverage_batch import make_game
from training.b_sft.online_social import OnlineSocial, VERSION
from training.b_sft.social_cases import key, P_INSTRUCTION
from training.b_sft.online_social_audit import verify

RECIPES = [dict(id='heldout-three', seed=420110, n=3, k=2, g=5, mode='single'),
           dict(id='heldout-four-small', seed=420111, n=4, k=1, g=5, mode='multi_partner'),
           dict(id='heldout-four', seed=420112, n=4, k=2, g=6, mode='multi_goal')]


def topology_id(raw):
    """Ignore seed/preferences/schedule/menu: renaming or timing isn't a new topology."""
    g = raw['game']; n = g['n_players']; counts = g['n_actions_per_player']; best = None
    for order in permutations(range(n)):
        pm = {p: i for i, p in enumerate(order)}
        for am in product(*(permutations(range(k)) for k in counts)):
            goals = sorted((x.get('binary', True), tuple(sorted((pm[a['player_id']], am[a['player_id']][a['action_id']])
                            for a in x['required_actions']))) for x in g['goals'])
            encoded = json.dumps(([counts[p] for p in order], goals))
            if best is None or encoded < best: best = encoded
    return hashlib.sha256(best.encode()).hexdigest()


def fixture(recipe, setup='pass'):
    raw, _ = make_game(recipe['seed'], recipe['n'], recipe['k'], recipe['g'], recipe['mode'])
    raw['id'] = recipe['id']; raw['game']['menu_enabled'] = False
    # Fixed model-blind setup: learner gets the penultimate proposal turn.
    order = raw['game']['round_robin']; n = recipe['n']
    pos = next(i for i in range(len(order)-n, len(order)) if order[i] == raw['ego'])
    order[pos], order[-2] = order[-2], order[pos]
    prefix = [dict(action='PASS') for _ in range(len(order)-2)]
    if setup != 'pass':
        if setup not in ('one_commitment', 'two_commitments'): raise ValueError('Unknown fixed setup')
        env = OnlineSocial(raw); desired = 1 if setup == 'one_commitment' else 2
        offers = [a.to_dict() for a in env.game.rules.actions(env.node) if a.to_dict().get('action') == 'OFFER']
        offers = [a for a in offers if sum(a['proposer_action'])+sum(a['partner_action']) == desired]
        chosen = random.Random(recipe['seed']+desired*1009).choice(offers)
        prefix = [chosen, dict(response='ACCEPT')] + prefix[1:]
    return raw, prefix


def build(training_pack, out):
    if out.exists(): raise ValueError('Use a new output directory')
    for path, expected in json.loads((training_pack/'checksums.json').read_text()).items():
        if hashlib.sha256((training_pack/path).read_bytes()).hexdigest() != expected:
            raise ValueError('Training material checksum mismatch')
    out.mkdir(parents=True); (out/'games').mkdir()
    frozen = dict(recipes=RECIPES, protocol=VERSION, partner_window=2, max_nodes=10000,
                  setups=['pass', 'one_commitment', 'two_commitments'],
                  setup='Public type-independent setup until learner penultimate proposal: either all PASS, or one fixed-seed legal offer accepted at the first turn, then PASS.',
                  selection='No model scores, no success-based regeneration. Retain flat/unavailable cases.',
                  branches='Native legal action indices 0, floor(N/3), floor(2N/3), N-1; independent of teacher values.')
    # Persist the recipes BEFORE computing labels or looking at outcomes.
    text = json.dumps(frozen, indent=2)+'\n'; (out/'frozen_recipes.json').write_text(text)
    train = {topology_id(json.loads(p.read_text())['fixture']) for p in (training_pack/'games').glob('*.json')}
    seen = set(); roots = []; rows = {}; trajectories = []; statuses = []; fixtures = {}
    for recipe in RECIPES:
        raw, _ = fixture(recipe); topology = topology_id(raw)
        if topology in train or topology in seen: raise ValueError('Holdout topology overlaps training/another recipe')
        seen.add(topology)
        fixtures[recipe['id']] = raw
        prefixes = {s: fixture(recipe, s)[1] for s in frozen['setups']}
        (out/'games'/f"{recipe['id']}.json").write_text(json.dumps(dict(fixture=raw, prefixes=prefixes, topology=topology), indent=2)+'\n')
        for setup, prefix in prefixes.items():
            collect_setup(raw, prefix, recipe, topology, setup, rows, roots, trajectories, statuses)
    for name, data in [('questions.jsonl', list(rows.values())), ('trajectories.jsonl', trajectories),
                       ('B_inputs.jsonl', [dict(id=r['id'], input=r['input']) for r in rows.values()]),
                       ('P_contexts.jsonl', [dict(id=r['id'], context=dict(r['input'], instruction=P_INSTRUCTION),
                                                belief_source='actual model B output required') for r in rows.values()])]:
        (out/name).write_text(''.join(json.dumps(x)+'\n' for x in data))
    pairs = {}
    for e in trajectories:
        for before, after in zip(e['snapshots'], e['snapshots'][1:]):
            a, b = rows[before]['teacher']['B_by_target'], rows[after]['teacher']['B_by_target']
            if a is None or b is None: continue
            answers = lambda bs: {(x['player'], x['goal']): x['answer'] for x in bs}
            pair = dict(before=before, after=after, category='maintain' if answers(a)==answers(b) else 'update')
            pairs[key(pair)] = pair
    (out/'pairs.jsonl').write_text(''.join(json.dumps(x)+'\n' for x in pairs.values()))
    summary = dict(split='development_generalization', protocol=VERSION, cases=statuses,
                   independent_topologies=len(seen), decisions=len(rows), trajectories=len(trajectories),
                   pairs=len(pairs), informative_B_questions=sum(any(len(b['answer']['possible_preferences']) < 3
                       for b in r['teacher']['B_by_target'] or []) for r in rows.values()),
                   training_overlap=False, frozen_recipes_sha256=hashlib.sha256(text.encode()).hexdigest(),
                   root_questions=roots, actual_LM=False, model_based_selection=False,
                   limits=['Small development check, not final transfer evidence.',
                           'Fixed public endgame setups and declared partner protocol; no claim of arbitrary unknown strategies.',
                           'Do not mix these rows into training or use them to select new generation recipes.'])
    summary['verification'] = verify(fixtures, list(rows.values()), trajectories)
    summary['pair_counts'] = {kind: sum(p['category']==kind for p in pairs.values()) for kind in ('maintain', 'update')}
    (out/'summary.json').write_text(json.dumps(summary, indent=2)+'\n')
    (out/'checksums.json').write_text(json.dumps({str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in out.rglob('*') if p.is_file()}, indent=2)+'\n')
    return summary


def collect_setup(raw, prefix, recipe, topology, setup, rows, roots, trajectories, statuses, *, score_p=True):
    env = OnlineSocial(raw, prefix); env.ensure_teacher(); root = env.context()
    root_p = env.p_reference_values(max_rollouts=512, seconds=20) if score_p else dict(mask=False, values=None, reason='B screening only')
    initial_actions = env.game.rules.actions(env.node)
    indices = sorted({0, len(initial_actions)//3, 2*len(initial_actions)//3, len(initial_actions)-1})
    count_before = len(rows); failures = 0
    for index in indices:
        for world in env.game.worlds:
            run = env.fork(); snapshots = []
            while not run.terminal:
                run.ensure_teacher()
                if run.actor == raw['ego']:
                    context = run.context(); rid = recipe['id']+'-'+key(context)
                    if rid not in rows:
                        values = root_p if len(run.history) == len(prefix) or not score_p else run.p_reference_values(max_rollouts=512, seconds=20)
                        rows[rid] = dict(id=rid, source=recipe['id'], setup=setup, topology=topology, split='development_generalization',
                                        input=context, teacher=dict(B_by_target=run.belief_table(), B_aux_mask=not(run.invalid_reason or run.fragile),
                                                                   P_reference=values))
                    snapshots.append(rid)
                    action = initial_actions[index] if len(run.history) == len(prefix) else run.reference_action(world[run.actor])
                    run.step(action, kind='learner')
                else:
                    action = run.reference_action(world[run.actor]); run.step(action, kind='partner')
            failures += bool(run.invalid_reason)
            trajectories.append(dict(source=recipe['id'], setup=setup, first_action_index=index, environment_world=world,
                                     snapshots=snapshots, history=run.history, events=run.events, utilities=run.outcome(world),
                                     usable=not bool(run.invalid_reason), unavailable=run.invalid_reason))
    roots.append(recipe['id']+'-'+key(root))
    statuses.append(dict(id=recipe['id'], setup=setup, topology=topology, worlds=len(env.game.worlds),
                         decisions=len(rows)-count_before, trajectories=len(indices)*len(env.game.worlds),
                         unavailable_trajectories=failures, root_P_available=root_p['mask']))
    print(json.dumps(statuses[-1]), flush=True)


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser(); p.add_argument('--training-pack', type=Path, default=Path('new/local_data/social_cases_v2'))
    p.add_argument('--output-dir', type=Path, required=True); a = p.parse_args()
    print(json.dumps(build(a.training_pack, a.output_dir), indent=2))
