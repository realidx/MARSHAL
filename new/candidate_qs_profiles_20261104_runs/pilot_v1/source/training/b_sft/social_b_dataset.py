"""Small B-only development corpus: authored cases and seeded native mining.

No LM calls, rationale targets, P labels, or training protocol changes. Sources,
public questions, private labels, temporal pairs and audit evidence stay separate.
"""
import argparse
from collections import Counter, defaultdict
from copy import copy, deepcopy
import hashlib
import json
from pathlib import Path
import random
import math
from itertools import product

from training.b_sft.social_b_oracle import BeliefOracle, VERSION, FAVORED_RULE, canonical, forward_fixture
from training.b_sft.social_cases import bundle_fixture
from training.b_sft.social_cases_expand import compensated_fixture
from training.b_sft.shared_teacher import SearchLimit, native
from benac_p.generator import GeneratorConfig, generate_game
from benac_p.endgame_diagnose import decode_action


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()[:20]


def judgment(answer):
    """The actual LM target; teacher probability audits are not output fields."""
    return dict(possible_preferences=sorted(answer['possible_preferences']), favored=answer['favored'])


def belief_changes(before, after):
    a, b = set(before['possible_preferences']), set(after['possible_preferences'])
    if not b or not b <= a:
        raise AssertionError('Nonmonotone or empty B support')
    weighted = 'preference_weights' in before and 'preference_weights' in after
    return dict(support_changed=a != b,
                favored_changed=before.get('favored', 'undetermined') != after.get('favored', 'undetermined'),
                weights_changed=weighted and any(not math.isclose(before['preference_weights'][v],
                    after['preference_weights'][v], abs_tol=1e-9, rel_tol=0) for v in ('want','neutral','avoid')))


def transition(before, after):
    changes = belief_changes(before, after)
    a, b = set(before['possible_preferences']), set(after['possible_preferences'])
    # Probability-only changes are audit events, not new LM output targets.
    # They must not be called unchanged beliefs or count as rewarded updates.
    if changes['favored_changed'] or b < a:
        return 'formation' if len(a) == 3 and before.get('favored', 'undetermined') == 'undetermined' else 'update'
    if changes['weights_changed']:
        return 'strength_change'
    if len(b) > 1 and after.get('favored', 'undetermined') != 'undetermined':
        return 'maintain'
    return 'maintain' if len(a) == 2 else 'uninformative' if len(a) == 3 else 'known_control'


def observer_belief(o, target, goal):
    return o.belief(target, goal, observer=o.raw['ego'], own=o.raw['own_preferences'])


def random_fixture(seed, hidden=None, layout='same_partner'):
    rng = random.Random(seed)
    if hidden is None:
        hidden, layout = rng.choice(((1, 'same_partner'), (2, 'same_partner'), (2, 'different_partners')))
    if hidden not in (1, 2) or layout not in ('same_partner', 'different_partners'):
        raise ValueError('Supported pilot: one/two hidden preferences, same/different partners')
    n = rng.choice((3, 4))
    spec = generate_game(seed, GeneratorConfig(n_players=n, actions_per_player=2,
                         n_goals=rng.randint(n+1, 2*n), n_rounds=2))
    ego = rng.randrange(n)
    target = rng.randrange(n)
    goal = rng.choice([g.goal_id for g in spec.goals])
    types = {str(p): [spec.private_preferences[p].tolist()] for p in range(n)}
    background = types[str(target)][0]
    types[str(target)] = [background[:goal] + [x] + background[goal+1:] for x in (1, 0, -1)]
    queries = [dict(player=target, goal=goal)]
    if hidden == 2:
        other = target if layout == 'same_partner' else rng.choice([p for p in range(n) if p != target])
        choices = [g.goal_id for g in spec.goals if other != target or g.goal_id != goal]
        if not choices: raise ValueError('No second distinct hidden preference slot')
        second = rng.choice(choices)
        queries.append(dict(player=other, goal=second))
        types[str(other)] = [row[:second]+[x]+row[second+1:]
                            for row in types[str(other)] for x in (1,0,-1)]
    raw = dict(id=f'random-{seed}', ego=ego, own_preferences=spec.private_preferences[ego].tolist(),
               history=[], type_catalogues=types, game=spec.to_dict())
    raw['hidden_queries'] = queries
    raw['generation'] = dict(seed=seed, players=n, goals=len(spec.goals), hidden=hidden, layout=layout,
                             hidden_players=sorted({q['player'] for q in queries}),
                             observer_hidden=any(q['player']==ego for q in queries))
    # Reject inadmissible candidate catalogues; never repair them using labels.
    rules, worlds, _ = native(raw)
    assert len(worlds) == 3 ** hidden
    assert {tuple(w[q['player']][q['goal']] for q in queries) for w in worlds} == set(product((1,0,-1), repeat=hidden))
    node = rules.initial(); prefix = []
    # Random commitments are reached by legal, preference-independent setup.
    for _ in range(rng.randrange(n)):
        offers = [a for a in rules.actions(node) if a.to_dict().get('action') == 'OFFER']
        action = rng.choice(offers or list(rules.actions(node)))
        prefix.append(action.to_dict()); node = rules._apply(node, action)
        if node.pending is not None:
            response = decode_action({'response': rng.choice(('ACCEPT', 'REJECT'))})
            prefix.append(response.to_dict()); node = rules._apply(node, response)
    raw['generation']['setup_commitments'] = sum(sum(row) for row in node.state.snapshot_commitments())
    return raw, prefix, target, goal


def question(o, target, goal, prefix):
    # A paused B checkpoint need not be the observer's own action turn.
    return dict(player=o.raw['ego'], own_preferences=o.raw['own_preferences'],
                game=o.rules.spec.to_dict(), public_state=o.node.state.public_state(),
                pending_offer=None if o.node.pending is None else o.node.pending.to_dict(),
                assessment=dict(phase='terminal' if o.node.state.is_terminal else
                                'response' if o.node.pending is not None else 'proposal',
                                observer_to_act=not o.node.state.is_terminal and o.rules.actor(o.node)==o.raw['ego'],
                                offer_status='awaiting_response_not_binding' if o.node.pending is not None else None),
                history=deepcopy(o.history), public_type_catalogues=o.raw['type_catalogues'],
                public_setup=dict(intervention_prefix=prefix,
                    semantics='Setup is imposed independently of preferences and is not evidence.'),
                partner_model=o.mechanism(),
                history_semantics='Every post-setup action is autonomous under the declared mechanism, including the observer actions.',
                queries=[dict(player=target, goal=goal)],
                favored_rule=FAVORED_RULE,
                instruction='Infer the queried partner preference from public history and your own preferences. '
                            'Return possible_preferences and favored. Do not choose an action or calculate utilities.')


def fork(o):
    child = copy(o)
    child.history = list(o.history)
    child.events = list(o.events)
    # Existing tree and events are read-only; observe appends and invalidates cache.
    return child


def mine(raw, prefix, target, goal, *, max_nodes=3000, beam=8, state_budget=80):
    root = BeliefOracle(raw, prefix, turns=2, max_nodes=max_nodes, seconds=2)
    initial = observer_belief(root, target, goal)
    if len(initial['possible_preferences']) != (1 if target == raw['ego'] else 3):
        raise ValueError('Partner queries start uncertain; the observer knows its own private row')
    records, labels, pairs, failures = {}, {}, [], []
    frontier = [(root, 0)]; visited = 0; terminals = 0; dropped = 0

    def save(o):
        inp = question(o, target, goal, prefix)
        rid = digest(inp)
        records[rid] = dict(id=rid, source=raw['id'], input=inp)
        labels[rid] = dict(id=rid, answer=observer_belief(o, target, goal),
                          joint_belief=o.joint_belief(observer=raw['ego'], own=raw['own_preferences']))
        return rid

    while frontier and visited < state_budget:
        following = []
        for o, shrinks in frontier:
            if visited >= state_budget:
                dropped += 1
                continue
            visited += 1
            if o.node.state.is_terminal:
                terminals += 1
                continue
            before = observer_belief(o, target, goal)
            try:
                actor = o.rules.actor(o.node)
                actions = {canonical(a): a for own in dict.fromkeys(w[actor] for w in o.worlds)
                           for a in o.choices(own)['admissible_actions']}
                children = []
                for key, action in sorted(actions.items()):
                    child = fork(o); child.observe(action)
                    # A mined public branch may exclude the specified private
                    # observer row; it cannot become a question for that observer.
                    if not any(w[raw['ego']] == tuple(raw['own_preferences']) for w in child.worlds):
                        continue
                    after = observer_belief(child, target, goal)
                    category = transition(before, after)
                    changes = belief_changes(before, after)
                    count = shrinks + int(changes['support_changed'])
                    children.append((child, count))
                    # Do not count an observer-only action as partner evidence.
                    if actor == raw['ego']:
                        continue
                    old, new = save(o), save(child)
                    pair = dict(before=old, after=new, category=category, source=raw['id'],
                                accumulated_shrinks=count, actor=actor,
                                changes=changes,
                                event=deepcopy(child.events[-1]),
                                witness_world=next(w for w in child.worlds if w[raw['ego']] == tuple(raw['own_preferences'])),
                                query=dict(player=target, goal=goal),
                                joint_support_changed=len(child.worlds)<len(o.worlds),
                                received_offer=child.node.pending is not None and
                                    child.node.pending.partner_id == raw['ego'],
                                observed_response='response' in action,
                                terminal_checkpoint=child.node.state.is_terminal)
                    pairs.append(pair)
                following.extend(children)
            except (SearchLimit, ValueError) as exc:
                failures.append(dict(history=deepcopy(o.history), error=type(exc).__name__, detail=str(exc)))
        # Keep some narrowed and some still-uncertain histories at each depth.
        buckets = defaultdict(list)
        for child, count in following:
            belief = observer_belief(child, target, goal)
            buckets[(count, len(belief['possible_preferences']), belief['favored'])].append((child, count))
        frontier = []
        for values in buckets.values():
            values.sort(key=lambda x: digest(x[0].history))
        while buckets and len(frontier) < beam:
            for key in sorted(list(buckets), reverse=True):
                if len(frontier) >= beam:
                    break
                frontier.append(buckets[key].pop(0))
                if not buckets[key]: del buckets[key]
        dropped += sum(len(v) for v in buckets.values())
    return records, labels, pairs, dict(visited=visited, terminal_nodes=terminals,
        pruned_nodes=dropped+len(frontier), failures=failures)


def validate_pair(raw, prefix, before, after, pair, labels):
    history = after['input']['history']
    events = [dict(action=a, kind='setup' if i < len(prefix) else 'partner')
              for i, a in enumerate(history)]
    o = BeliefOracle.replay(raw, events, turns=2, max_nodes=3000, seconds=2)
    query = after['input']['queries'][0]
    target, goal = query['player'], query['goal']
    assert observer_belief(o, target, goal) == labels[after['id']]['answer']
    assert o.joint_belief(observer=raw['ego'], own=raw['own_preferences']) == labels[after['id']]['joint_belief']
    # Persisted JSON uses lists where the in-memory oracle uses tuples.
    assert canonical(o.events[-1]) == canonical(pair['event'])
    assert before['input']['history'] == history[:-1]
    p = BeliefOracle.replay(raw, events[:-1], turns=2, max_nodes=3000, seconds=2)
    assert observer_belief(p, target, goal) == labels[before['id']]['answer']
    assert transition(labels[before['id']]['answer'], labels[after['id']]['answer']) == pair['category']
    assert tuple(map(tuple, pair['witness_world'])) in o.worlds
    assert tuple(pair['witness_world'][raw['ego']]) == tuple(raw['own_preferences'])
    rules, _, _ = native(raw); node = rules.initial()
    for a in history:
        node = rules._apply(node, decode_action(a))
    assert node.state.public_state() == after['input']['public_state']
    assert (None if node.pending is None else node.pending.to_dict()) == after['input']['pending_offer']


def build(out, seeds=18, start_seed=920000, base=None, hidden=0, layout='same_partner'):
    if out.exists(): raise ValueError('Use a new output directory')
    out.mkdir(parents=True)
    def write(name, rows):
        (out/name).write_text(''.join(json.dumps(r, ensure_ascii=False)+'\n' for r in rows))
    paths = [Path(__file__), Path('training/b_sft/social_b_oracle.py'), Path('training/b_sft/shared_teacher.py'),
             Path('training/b_sft/catalogues.py'),
             Path('training/b_sft/social_b_random_window.py'),
             Path('third_party/negotiation_benchmark/src/benac_p/generator.py')]
    hashes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    sources, attempts, records, labels, all_pairs = {}, [], {}, {}, []
    if base is not None:
        manifest = base/'summary.json' if (base/'summary.json').exists() else base/'candidate_manifest.json'
        previous = json.loads(manifest.read_text())
        if previous['version'] != VERSION: raise ValueError('Cannot reuse labels from another oracle version')
        if previous.get('hidden_preferences', 1) != hidden: raise ValueError('Do not mix hidden-dimension pilots')
        for path, checksum in previous['source_hashes'].items():
            if Path(path).name != Path(__file__).name and hashlib.sha256(Path(path).read_bytes()).hexdigest() != checksum:
                raise ValueError(f'Cannot reuse labels after mechanism change: {path}')
        def read(name): return [json.loads(line) for line in (base/name).read_text().splitlines()]
        sources = {s['id']: {k:v for k,v in s.items() if k!='id'} for s in read('sources.jsonl')}
        attempts = read('attempts.jsonl')
        records = {r['id']:r for r in read('all_candidate_inputs.jsonl')}
        labels = {r['id']:r for r in read('all_candidate_labels.jsonl')}
        all_pairs = read('all_candidate_pairs.jsonl')
        # Category definitions can evolve independently of identical oracle
        # gold. Recompute them rather than carrying stale curriculum metadata.
        for p in all_pairs:
            p['category'] = transition(labels[p['before']]['answer'], labels[p['after']]['answer'])
            p['changes'] = belief_changes(labels[p['before']]['answer'], labels[p['after']]['answer'])
    authored = [('forward', *forward_fixture(), 1, 2),
                ('forward_long', *forward_fixture(rounds=2), 1, 2),
                ('bundle', *bundle_fixture(), 1, 0),
                ('compensated', *compensated_fixture(), 1, 0)]
    jobs = [('authored', name, (raw, prefix, target, goal)) for name, raw, prefix, target, goal in authored] if hidden in (0,1) else []
    layouts = ('mixed',) if hidden == 0 else ('same_partner', 'different_partners') if layout == 'both' else (layout,)
    jobs += [('random', f'random-{s}-mixed' if hidden==0 else f'random-{s}' if hidden==1 else f'random-{s}-h2-{mode}', (s, mode))
             for mode in layouts for s in range(start_seed, start_seed+seeds)]
    for method, name, job in jobs:
        if name in {a['source'] for a in attempts}: continue
        try:
            raw, prefix, target, goal = random_fixture(job[0], hidden or None, job[1]) if method == 'random' else job
            raw = deepcopy(raw); raw['id'] = name
            queries = raw.get('hidden_queries', [dict(player=target, goal=goal)])
            source_pairs, audits = [], []
            for query in queries:
                r, l, pairs, audit = mine(raw, prefix, query['player'], query['goal'])
                records.update(r); labels.update(l); all_pairs.extend(pairs)
                source_pairs.extend(pairs); audits.append(dict(query=query, **audit))
            sources[name] = dict(raw=raw, prefix=prefix, target=target, goal=goal, method=method,
                                 queries=queries, initial_joint_worlds=len(native(raw)[1]),
                                 split='development', grouping='Keep all histories and branches of this source together')
            attempts.append(dict(source=name, method=method, status='mined', counts=dict(Counter(p['category'] for p in source_pairs)),
                                 query_audits=audits,
                                 failures=[f for a in audits for f in a['failures']]))
        except (SearchLimit, ValueError, RuntimeError) as exc:
            attempts.append(dict(source=name, method=method, status='failed', error=type(exc).__name__, detail=str(exc)))
        print(json.dumps(attempts[-1], default=str), flush=True)
    # Persist candidate work before slower validation and sampled continuations.
    # This checkpoint is not a reviewed/training-ready export.
    write('all_candidate_pairs.jsonl', all_pairs)
    write('all_candidate_inputs.jsonl', records.values()); write('all_candidate_labels.jsonl', labels.values())
    write('sources.jsonl', [dict(id=k, **v) for k,v in sources.items()]); write('attempts.jsonl', attempts)
    (out/'candidate_manifest.json').write_text(json.dumps(dict(version=VERSION, training_ready=False,
        stage='candidates_before_validation', hidden_preferences=hidden, source_hashes=hashes), indent=2)+'\n')
    excluded_updates = []
    def history_dependent(pair):
        source = sources[pair['source']]; after = records[pair['after']]['input']
        q = pair['query']; history = after['history']
        try:
            last = BeliefOracle(source['raw'], history[:-1], max_nodes=3000, seconds=2)
            last.observe(history[-1])
            if judgment(observer_belief(last,q['player'],q['goal'])) == judgment(labels[pair['after']]['answer']):
                excluded_updates.append(dict(pair=pair,reason='last_action_sufficient')); return False
        except (SearchLimit, ValueError) as exc:
            excluded_updates.append(dict(pair=pair,reason='history_dependence_unresolved',detail=str(exc))); return False
        return True
    # Equal caps do not imply balance. Do not duplicate missing categories.
    per_source = []
    for source in sources:
        for kind in ('formation', 'maintain', 'update', 'uninformative', 'strength_change', 'known_control'):
            candidates = [p for p in all_pairs if p['source']==source and p['category']==kind]
            candidates.sort(key=lambda p: (not p.get('received_offer', False), len(records[p['after']]['input']['history']), p['after']))
            accepted = 0
            for candidate in candidates:
                if kind == 'update' and not history_dependent(candidate): continue
                per_source.append(candidate); accepted += 1
                if accepted >= (3 if kind != 'uninformative' else 1): break
    selected = []
    for kind, cap in [('formation', 25), ('maintain', 25), ('update', 25), ('uninformative', 13),
                      ('strength_change', 13), ('known_control', 8)]:
        buckets = defaultdict(list)
        for p in per_source:
            if p['category'] == kind: buckets[p['source']].append(p)
        chosen = 0
        while buckets and chosen < cap:
            for source in list(buckets):
                if chosen >= cap: break
                selected.append(buckets[source].pop(0)); chosen += 1
                if not buckets[source]: del buckets[source]
    ids = {p[k] for p in selected for k in ('before', 'after')}
    for pair in selected:
        s = sources[pair['source']]
        validate_pair(s['raw'], s['prefix'], records[pair['before']], records[pair['after']], pair, labels)
    screened = selected
    screened_ids = {p[k] for p in screened for k in ('before','after')}
    # Same exact prior history, different next autonomous action and B answer.
    matched = []
    by_before = defaultdict(list)
    for p in all_pairs: by_before[p['before']].append(p)
    for before, group in by_before.items():
        for i, a in enumerate(group):
            for b in group[i+1:]:
                if labels[a['after']]['answer'] != labels[b['after']]['answer'] and a['after'] in ids and b['after'] in ids:
                    matched.append(dict(before=before, left=a['after'], right=b['after'], source=a['source']))
    sampled, sampling_failures = [], []
    for name, source in sources.items():
        raw, prefix = source['raw'], source['prefix']
        _, worlds, _ = native(raw)
        for wi, world in enumerate(worlds):
            if world[raw['ego']] != tuple(raw['own_preferences']): continue
            o = BeliefOracle(raw, prefix, turns=2, max_nodes=3000, seconds=2)
            rng = random.Random(f'{start_seed}:{name}:{wi}')
            try:
                while not o.node.state.is_terminal:
                    actor = o.rules.actor(o.node)
                    o.observe(o.sample_action(world[actor], rng))
                    assert world in o.worlds
                replay = BeliefOracle.replay(raw, o.events, turns=2, max_nodes=3000, seconds=2)
                assert replay.worlds == o.worlds
                assert replay.weights == o.weights
                sampled.append(dict(source=name, world=world, history=o.history,
                                    terminal=True, final_belief=observer_belief(o, source['target'], source['goal']),
                                    final_beliefs=[dict(query=q, answer=observer_belief(o, q['player'],q['goal']))
                                                  for q in source.get('queries', [dict(player=source['target'], goal=source['goal'])])]))
            except (SearchLimit, ValueError) as exc:
                sampling_failures.append(dict(source=name, world=world, history=o.history,
                                              error=type(exc).__name__, detail=str(exc)))
    summary = dict(version=VERSION, split='development', training_ready=False, actual_LM=False,
        hidden_preferences=hidden, hidden_layout=layout,
        reused_candidates_from=None if base is None else str(base),
        sources=len(sources), attempts=len(attempts), selected_questions=len(ids), selected_pairs=len(selected),
        categories=dict(Counter(p['category'] for p in selected)),
        screened_categories=dict(Counter(p['category'] for p in screened)),
        screened_update_favored=dict(Counter(labels[p['after']]['answer']['favored'] for p in screened if p['category']=='update')),
        excluded_updates=len(excluded_updates),
        by_method={m: dict(Counter(p['category'] for p in selected if sources[p['source']]['method']==m)) for m in ('authored','random')},
        support_sizes=dict(Counter(len(labels[i]['answer']['possible_preferences']) for i in ids)),
        matched_pairs=len(matched), validated_pairs=len(selected),
        multiple_shrink_pairs=sum(p['accumulated_shrinks'] >= 2 for p in selected),
        update_sources=len({p['source'] for p in selected if p['category']=='update'}),
        received_offer_pairs=sum(p.get('received_offer', False) for p in selected),
        received_offer_categories=dict(Counter(p['category'] for p in selected if p.get('received_offer',False))),
        observed_response_pairs=sum(p.get('observed_response',False) for p in selected),
        marginal_unchanged_joint_shrink=sum(p.get('joint_support_changed',False) and
            p['category'] not in ('formation','update') for p in selected),
        sampled_terminal_paths=len(sampled), sampled_failures=len(sampling_failures),
        limitations=['Development only; no held-out split or balancing claim.',
          'One/two initially independent hidden slots, including observer slots; all are jointly weighted. Questions query marginals, not full joint LM outputs.',
          'Bounded beam explores compatible histories, not natural-frequency trajectory sampling.',
          'Labels conditional on the selected bounded oracle; replay is not independent proof of its behavioral assumptions.',
          'Temporal checkpoints may be terminal; no P or outcome training labels.',
          'Strength-only changes are teacher audits, not supervised probability outputs. Full-set equal-weight controls remain separate.'])
    def coverage(names):
        rows = [sources[name]['raw'] for name in names]
        return dict(players=dict(Counter(r['game']['n_players'] for r in rows)),
                    goals=dict(Counter(len(r['game']['goals']) for r in rows)),
                    hidden_slots=dict(Counter(sum(len({row[g] for row in catalogue}) > 1
                        for catalogue in r['type_catalogues'].values() for g in range(len(r['game']['goals']))) for r in rows)),
                    hidden_players=dict(Counter(sum(len(c)>1 for c in r['type_catalogues'].values()) for r in rows)),
                    observer_hidden=dict(Counter(len(r['type_catalogues'][str(r['ego'])])>1 for r in rows)),
                    setup_commitments=dict(Counter(r.get('generation',{}).get('setup_commitments','authored') for r in rows)))
    summary['coverage_before_selection'] = coverage(sources)
    summary['coverage_after_selection'] = coverage({p['source'] for p in selected})
    summary['favored_with_multiple_possible'] = sum(len(labels[i]['answer']['possible_preferences'])>1 and
        labels[i]['answer']['favored']!='undetermined' for i in ids)
    write('B_inputs.jsonl', [records[i] for i in sorted(ids)])
    write('B_labels.jsonl', [labels[i] for i in sorted(ids)])
    write('pairs.jsonl', selected); write('matched_pairs.jsonl', matched)
    write('screened_pairs.jsonl', screened); write('excluded_updates.jsonl', excluded_updates)
    write('screened_B_inputs.jsonl', [records[i] for i in sorted(screened_ids)])
    write('screened_B_labels.jsonl', [labels[i] for i in sorted(screened_ids)])
    write('all_candidate_pairs.jsonl', all_pairs)
    write('all_candidate_inputs.jsonl', records.values()); write('all_candidate_labels.jsonl', labels.values())
    write('sources.jsonl', [dict(id=k, **v) for k,v in sources.items()]); write('attempts.jsonl', attempts)
    write('sampled_rollouts.jsonl', sampled); write('sampling_failures.jsonl', sampling_failures)
    summary['source_hashes'] = hashes
    (out/'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--seeds', type=int, default=18)
    parser.add_argument('--start-seed', type=int, default=920000)
    parser.add_argument('--base', type=Path)
    parser.add_argument('--hidden', type=int, choices=(0,1,2), default=0,
                        help='0 randomly mixes all three hidden-slot layouts; 1/2 constrain slot count')
    parser.add_argument('--layout', choices=('same_partner','different_partners','both'), default='same_partner')
    args = parser.parse_args()
    build(args.out, args.seeds, args.start_seed, args.base, args.hidden, args.layout)
