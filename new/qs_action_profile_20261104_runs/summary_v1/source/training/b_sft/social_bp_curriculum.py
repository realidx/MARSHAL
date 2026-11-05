"""Small, staged B/P curriculum under the selected full-terminal teacher.

CPU-only construction and audits. No model calls or optimizer integration.
Short behavioral updates and result-use exercises need not pass a full VOI
ablation. Exact worlds and Q values stay in labels, outside model requests.
"""
import argparse
from collections import Counter, defaultdict
from copy import copy, deepcopy
import hashlib
import json
from pathlib import Path

import numpy as np

from training.b_sft.shared_teacher import SearchLimit, TOL
from training.b_sft.social_b_oracle import canonical, forward_fixture
from training.b_sft.social_terminal_teacher import TerminalEpisode, Investigate, VERSION as TEACHER_VERSION, GAME_VERSION
from training.b_sft.social_b_curriculum import family
from training.b_sft.debug.audit_social_design_iteration import fixture, belief_examples, independent_values
from training.b_sft.debug.audit_investigation_value import information_value_fixture

VERSION = 'social-bp-short-curriculum-v1'
OWN_TOLERANCE = .1
SOCIAL_TOLERANCE = .1  # Total utility of others, not per-player average.
TOLERANCE_GRID = (0., .05, .1, .25)
NAMES = {1: 'want', 0: 'neutral', -1: 'avoid'}
POLICY = ('All players use the same selected full-terminal contingent policy. '
          'Start with uniform action choices and synchronously update player best responses to a stable policy. '
          'Each player knows its own preferences and public information only. '
          'Maximize expected own final goal utility, only at offer responses then expected sum of others utility on exact own ties, '
          'then choose uniformly among residual tied native actions. Execute that policy throughout the episode. '
          'This selection procedure does not assert a unique rational strategy. Setup actions are interventions, not behavioral evidence.')
RULES = ('Goal requirements are a conjunction: a goal is achieved only when every required commitment is made. '
         'Commitment vectors are in each named player\'s action-index order; 1 means committed, 0 means uncommitted. '
         'Commitments cannot be withdrawn. Preferences are fixed: an achieved goal contributes +1 for want, '
         '0 for neutral, -1 for avoid; an unachieved goal contributes zero. Add contributions across goals. '
         'An OFFER specifies the resulting commitment vectors of proposer and partner. ACCEPT executes it; '
         'REJECT leaves commitments unchanged. A proposal and its response consume one proposal turn together. '
         'PASS consumes the proposal turn. Follow the declared round-robin schedule to its real end. '
         'INVESTIGATE selects another player and one unknown goal preference: the environment publicly reveals '
         'that one true preference, consumes the proposal turn, changes no commitments, and uses the single '
         'shared investigation quota for the whole game. No MENU is available. '
         'Preference rows use the displayed goal order. Own preferences belong only to the named player.')


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()[:20]


def acceptable(values, actor, own_tolerance=OWN_TOLERANCE, social_tolerance=SOCIAL_TOLERANCE, *, actions=()):
    if any(not np.isfinite(t) or t < 0 for t in (own_tolerance, social_tolerance)):
        raise ValueError('Finite nonnegative tolerances required')
    values = np.asarray(values, dtype=float)
    own = values[:, actor]
    from training.b_sft.decision_policy import is_offer_response
    social = values.sum(axis=1)-own if is_offer_response(actions) else np.zeros_like(own)
    return [i for i, v in enumerate(own) if own.max()-v <= own_tolerance+TOL
            and all(social[j]-social[i] <= social_tolerance+TOL
                    for j, u in enumerate(own) if abs(u-v) <= TOL)]


def clone_episode(e):
    b = copy(e)
    b.events = deepcopy(e.events)
    b.weights = e.weights.copy()
    return b


def p_task(e, own):
    """Supply complete joint belief, never a hidden point behind vague language.

    This first multi-turn curriculum only renders equal public support. Unequal
    posteriors are reported as an input-coverage gap, not misdescribed or rounded.
    Existing qualitative final-turn certificates remain a separate audit.
    """
    if e.tree.certificate['diagnostic_policy']:
        raise ValueError('Diagnostic teacher cannot generate curriculum')
    ids = np.flatnonzero(e.weights > 0)
    if not np.allclose(e.weights[ids], e.weights[ids[0]], atol=TOL, rtol=0):
        return None
    row = e.choices(own)
    actor = row['actor']
    entry = e.tree.entries[e.index]
    public_worlds = [e.tree.worlds[i] for i in ids]
    own_worlds = [w for w in public_worlds if w[actor] == tuple(own)]
    situations = lambda ws: [[[NAMES[v] for v in r] for r in w] for w in ws]
    investigation = next((x for x in entry.node.state.public_state()['transcript']
                          if x['action'] == 'INVESTIGATE'), None)
    quota = entry.node.state.public_state()['investigation_remaining']
    remaining = len(e.rules.spec.round_robin)-entry.node.state.turn_index
    if investigation:
        skill, stage = 'result_use', 1
    elif any(a.get('action') == 'INVESTIGATE' for a in row['actions']):
        skill, stage = 'investigation_decision', 2
    else:
        skill = 'complete_belief' if len(own_worlds) == 1 else 'incomplete_belief'
        stage = 0 if len(own_worlds) == 1 and remaining == 1 else 1
    accepted = acceptable(row['values'], actor, actions=row['actions'])
    sensitivities = []
    for ot in TOLERANCE_GRID:
        for st in TOLERANCE_GRID:
            keep = acceptable(row['values'], actor, ot, st, actions=row['actions'])
            sensitivities.append(dict(own_tolerance=ot, social_tolerance=st,
                acceptable_actions=[row['actions'][i] for i in keep],
                all_legal_accepted=len(keep) == len(row['actions']),
                first_ordinary_accepted=next((i for i,a in enumerate(row['actions']) if a.get('action')!='INVESTIGATE'),None) in keep,
                pass_accepted=any(row['actions'][i].get('action') == 'PASS' for i in keep),
                noninvestigation_accepted=any(row['actions'][i].get('action') != 'INVESTIGATE' for i in keep)))
    inp = dict(player=actor, own_preferences=[NAMES[v] for v in own],
        game=e.rules.public_game(), current_state=entry.node.state.public_state(),
        pending_offer=entry.node.pending.to_dict() if entry.node.pending else None,
        reference_policy_context=dict(initial_setup=deepcopy(e.setup),
            initial_public_joint_alternatives=situations(e.tree.worlds),
            initial_support='Equal support over these public alternatives at policy selection, after the imposed setup.',
            history_since_selection=deepcopy(e.events),
            instruction='The reference policy was selected after initial_setup and remains fixed. Setup is legal imposed context, not evidence of voluntary teacher choices. Use the supplied CURRENT belief for this decision.'),
        supplied_belief=dict(public_joint_alternatives=situations(public_worlds),
            your_joint_alternatives=situations(own_worlds),
            support='Each listed public alternative has equal current support. Your alternatives additionally condition on your own preferences. Every other player conditions the public alternatives on their own preferences.',
            instruction='Use this supplied current belief directly; do not reconstruct it from history.'),
        partner_policy=POLICY, legal_actions=row['actions'],
        instruction='Choose an action using the supplied belief and subsequent interactions through the real end of this game. First prefer your own final utility, only when responding to an offer help others when your own utilities tie.')
    teacher = dict(acceptable_actions=[row['actions'][i] for i in accepted], action_values=row['values'],
        own_tolerance=OWN_TOLERANCE, social_tolerance=SOCIAL_TOLERANCE,
        sensitivity=sensitivities, policy_sha256=e.tree.certificate['policy_sha256'],
        entry_index=e.index, remaining_proposal_turns=remaining,
        all_legal_accepted=len(accepted) == len(row['actions']),
        investigator=investigation['proposer_id'] if investigation else None,
        investigation_remaining=quota)
    return dict(task='P', skill=skill, stage=stage, input=inp, teacher=teacher,
                source=e.raw['id'], training_ready=False)


def p_examples(episode, *, max_events=4):
    tasks, skipped = [], Counter()
    def walk(e):
        entry = e.tree.entries[e.index]
        if entry.actor is None:
            return
        own_types = dict.fromkeys(w[entry.actor] for i, w in enumerate(e.tree.worlds) if e.weights[i] > 0)
        for own in own_types:
            task = p_task(e, own)
            if task is None:
                skipped['unequal_public_belief_needs_qualitative_certificate'] += 1
            else:
                tasks.append(task)
        if len(e.events) >= max_events:
            return
        for ai, action in enumerate(entry.actions):
            if not np.dot(e.weights, e.tree.policy[e.index][ai]) > 0:
                continue
            outcomes = [None]
            if isinstance(action, Investigate):
                outcomes = [x.value for x in e.tree.entries[entry.children[ai]].actions]
            for value in outcomes:
                branch = clone_episode(e)
                try:
                    branch.observe(action.to_dict(), revelation=value)
                except ValueError as exc:
                    if 'incompatible' not in str(exc):
                        raise
                    continue
                walk(branch)
    walk(episode)
    return tasks, dict(skipped)


def result_pairs(tasks):
    """Matched post-revelation exercises, not a causal proof of total query VOI.

    Match all observed actions/commitments/own type; only revelation and supplied
    belief may differ. Keep pairs whose acceptable sets are disjoint at 0.1/0.1.
    This test does not demand that directly reading a revelation be indispensable.
    """
    groups = defaultdict(list)
    for t in tasks:
        if t['task'] != 'P' or t['skill'] != 'result_use':
            continue
        inp = deepcopy(t['input'])
        inp.pop('supplied_belief')
        inp['reference_policy_context'].pop('initial_public_joint_alternatives')
        for ev in inp['current_state']['transcript']:
            ev.pop('revealed_preference', None)
        for ev in inp['reference_policy_context']['initial_setup']:
            ev.pop('revealed_preference', None)
        for ev in inp['reference_policy_context']['history_since_selection']:
            ev.pop('revelation', None)
        groups[(t.get('contrast_family',t['source']), digest(inp))].append(t)
    pairs = []
    for group in groups.values():
        for i, a in enumerate(group):
            for b in group[i+1:]:
                if {canonical(x) for x in a['teacher']['acceptable_actions']} & {canonical(x) for x in b['teacher']['acceptable_actions']}:
                    continue
                pairs.append(dict(kind='result_use', members=[a['id'], b['id']],
                    investigator_is_decision_maker=a['teacher']['investigator'] == a['input']['player'],
                    scope='Different supplied revelations require different actions at matched observed behavior and physical state; not a direct-read necessity ablation.',
                    tolerance_survival=[dict(own_tolerance=x['own_tolerance'], social_tolerance=x['social_tolerance'],
                        disjoint=not bool({canonical(v) for v in x['acceptable_actions']} & {canonical(v) for v in y['acceptable_actions']}))
                        for x, y in zip(a['teacher']['sensitivity'], b['teacher']['sensitivity'])]))
    return pairs


def result_use_fixture(value):
    """One legal final proposal after a public query. Setup is not teacher evidence.

    A risky deal achieves two own wanted goals if the partner wants goal 0;
    otherwise the partner rejects it and a different safe deal is better.
    No extra behavior type, noisy response, reward weight or non-native goal.
    """
    raw = dict(id='investigator-result-use-'+value, ego=0, own_preferences=[1,1,1], history=[],
        type_catalogues={'0':[[1,1,1]], '1':[[1,0,1],[-1,0,1]], '2':[[1,0,0]]},
        game=dict(n_players=3, n_actions_per_player=[2,1,1], max_changes=1, menu_enabled=False,
            round_robin=[2,1,0]*2,
            goals=[dict(goal_id=i,binary=True,required_actions=[dict(player_id=p,action_id=a) for p,a in req])
                   for i,req in enumerate([[(0,0),(1,0)],[(0,0),(1,0),(2,0)],[(0,1),(1,0)]])]))
    prefix = [dict(action='OFFER',partner_id=1,proposer_action=[1],partner_action=[0]),
        dict(response='ACCEPT'),dict(action='PASS'),
        dict(action='INVESTIGATE',player=1,goal=0,revealed_preference=value),
        dict(action='PASS'),dict(action='PASS')]
    return raw,prefix


def sources():
    # A deliberately small set of mechanisms. Preference changes stay together
    # with every checkpoint; player renamings are not independent examples.
    for seed in (104, 5, 8, 6):
        raw, prefix = fixture(seed, three_types=True)
        yield raw, prefix, 'pair_and_joint', 'train' if seed in (104,5) else 'validation_configuration'
    raw, prefix = fixture(104, hidden=2)
    yield raw, prefix, 'pair_and_joint', 'train'
    for deadline in (False, True):
        raw, prefix = information_value_fixture(deadline=deadline)
        yield raw, prefix, 'pair_and_joint', 'train'
    raw, prefix = information_value_fixture(extra_target=True)
    yield raw, prefix, 'pair_and_joint_with_completed_goal', 'validation_structure'
    for deadline in (False, True):
        raw, prefix = forward_fixture(deadline=deadline)
        raw['id'] += '-curriculum'+('-deadline' if deadline else '')
        yield raw, prefix, 'opportunity', 'train'
        complete = deepcopy(raw)
        complete['id'] += '-complete'
        complete['type_catalogues'] = {p: [rows[0]] for p, rows in raw['type_catalogues'].items()}
        yield complete, prefix, 'opportunity', 'train'
    for value in ('want','avoid'):
        raw,prefix = result_use_fixture(value)
        yield raw,prefix,'result_use_bridge','train'


def prepare_b(t):
    t = deepcopy(t)
    t['task'] = 'B'
    inp = t['input']
    inp['queries'] = [inp.pop('query')]
    t['skill'] = inp['task']
    t['stage'] = 0 if t['skill'] == 'formation' and len(inp['history']) == 1 else 1
    t['teacher'] = dict(gold=t.pop('gold'), weights=t.pop('teacher_only_weights'),
                        policy_sha256=t.pop('teacher_policy_sha256'))
    query = inp['queries'][0]
    initial_candidates = {NAMES[row[query['goal']]] for row in inp['public_type_catalogues'][str(query['player'])]}
    t['teacher']['default_full_set_correct'] = (
        set(t['teacher']['gold']['possible_preferences']) == initial_candidates
        and t['teacher']['gold']['favored'] == 'undetermined')
    inp['favored_rule'] = ('possible_preferences contains exactly the candidates with nonzero support. '
        'favored is the uniquely most supported preference, including for multi-element sets; '
        'use undetermined when the largest supports tie. A singleton favors its only member.')
    return t


def b_pairs_and_sequences(tasks):
    formations = {}
    groups = defaultdict(list)
    for t in tasks:
        if t['task'] != 'B':
            continue
        inp = t['input']
        query = canonical(inp['queries'])
        if t['skill'] == 'formation':
            formations[(t['source'], query, canonical(inp['history']))] = t
        else:
            groups[(t['source'], query, canonical(inp['old_history']))].append(t)
    pairs, sequences = [], []
    for group in groups.values():
        keep = next((t for t in group if t['skill'] == 'maintain'), None)
        change = next((t for t in group if t['skill'] == 'update'), None)
        if keep and change:
            pairs.append(dict(kind='maintain_vs_update', members=[keep['id'], change['id']]))
    for t in tasks:
        if t['task'] != 'B' or t['skill'] != 'update':
            continue
        inp = t['input']
        keys = [(t['source'], canonical(inp['queries']), canonical(inp['history'][:k]))
                for k in range(1, len(inp['history'])+1)]
        if len(keys) > 1 and all(k in formations for k in keys):
            ids = [formations[k]['id'] for k in keys]
            sequences.append(dict(id=digest(ids), source=t['source'], split=t['split'], stage=2,
                checkpoints=ids, prior_answers='Retain actual model answers, never inject previous gold.'))
    return pairs, list({s['id']:s for s in sequences}.values())


def build(out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    tasks, reports, source_rows = [], [], []
    for raw, prefix, mechanism, split in sources():
        report = dict(source=raw['id'], mechanism=mechanism, split=split)
        source_rows.append(dict(raw=raw, prefix=prefix, mechanism=mechanism, split=split, topology=family(raw)))
        try:
            e = TerminalEpisode(raw, prefix, max_nodes=30000, seconds=12)
            report.update(status='solved', native=independent_values(e.tree), nodes=len(e.tree.entries),
                          certificate=e.tree.certificate)
            current = []
            for player, rows in raw['type_catalogues'].items():
                if mechanism == 'result_use_bridge':
                    continue
                for goal in range(len(rows[0])):
                    if len({r[goal] for r in rows}) > 1:
                        current.extend(prepare_b(t) for t in belief_examples(e, int(player), goal, max_per_kind=8))
            p, skipped = p_examples(e)
            current.extend(p)
            report['input_gaps'] = skipped
            for t in current:
                t.update(mechanism=mechanism, topology=family(raw), split=split)
                if mechanism == 'result_use_bridge':
                    t['contrast_family'] = 'investigator-result-use'
                    t['teacher']['setup_scope'] = 'Public query and intervening actions are legal imposed setup, not claimed teacher-optimal choices. Only the remaining decision is supervised.'
                t['id'] = digest((VERSION, t['source'], t['task'], t['input']))
            # Limit repeated equivalent practice, preserving all contrasting
            # result-use members. Repetition happens by resampling, not copies.
            rp = result_pairs(current)
            required = {i for pair in rp for i in pair['members']}
            counts = Counter()
            selected = []
            for t in sorted(current, key=lambda x: (x['stage'], x['id'])):
                key = (t['task'], t.get('category', t['skill']), t['stage'],
                       t['input'].get('queries', [{}])[0].get('player'))
                if counts[key] < 8 or t['id'] in required:
                    selected.append(t)
                    counts[key] += 1
            tasks.extend(selected)
            report['tasks'] = len(selected)
        except SearchLimit as exc:
            report.update(status='solver_failure', reason=str(exc))
        reports.append(report)
        print(json.dumps({k:v for k,v in report.items() if k in ('source','status','tasks','reason')}), flush=True)
    tasks = list({t['id']:t for t in tasks}.values())
    pairs = result_pairs(tasks)
    bp, sequences = b_pairs_and_sequences(tasks)
    pairs += bp
    sensitive = {tid for p in pairs if p['kind']=='result_use' for tid in p['members']}
    for t in tasks:
        if t['task']=='P':
            t['teacher']['matched_result_use_certified'] = t['id'] in sensitive
            t['practice_role'] = ('protocol_only' if t['teacher']['all_legal_accepted'] else
                'matched_information_use' if t['id'] in sensitive else 'decision_practice')
    by_id = {t['id']:t for t in tasks}
    for pair in pairs:
        assert len({by_id[i]['split'] for i in pair['members']}) == 1
    train_topologies = {t['topology'] for t in tasks if t['split'] == 'train'}
    assert not train_topologies & {t['topology'] for t in tasks if t['split'] == 'validation_structure'}
    summary = dict(version=VERSION, teacher_version=TEACHER_VERSION, game_version=GAME_VERSION,
        actual_LM=False, training_ready=False, eval_steps=10,
        tolerance=dict(own=OWN_TOLERANCE, social_sum=SOCIAL_TOLERANCE, status='pilot, not empirically calibrated'),
        tasks=len(tasks), source_statuses=dict(Counter(r['status'] for r in reports)),
        coverage=dict(Counter(f"{t['split']}/{t['task']}/{t['stage']}/{t.get('category',t['skill'])}" for t in tasks)),
        result_use_pairs=sum(p['kind']=='result_use' for p in pairs),
        investigator_result_use_pairs=sum(p.get('investigator_is_decision_maker',False) for p in pairs),
        maintain_update_pairs=len(bp), continuous_sequences=len(sequences),
        all_legal_accepted=sum(t['teacher'].get('all_legal_accepted',False) for t in tasks),
        b_default_full_set_correct=sum(t['teacher'].get('default_full_set_correct',False) for t in tasks),
        provisional_stage_note='Stage numbers express intended prerequisites, not measured model difficulty.',
        scope='Small developmental curriculum; inspected held-out configurations/structures are not a blind benchmark. No claim of measured LM difficulty or transfer.',
        open_issues=['Unequal qualitative multi-turn beliefs need sufficient-input certificates',
                     'Sampling must verify actual difficulty; stage labels are design hypotheses',
                     'No optimizer export or LM endpoint invocation in this CPU build'],
        source_sha256={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in
            [Path(__file__), Path('training/b_sft/social_terminal_teacher.py'),
             Path('training/b_sft/debug/audit_social_design_iteration.py')]})
    for name, rows in [('tasks.jsonl',tasks),('contrasts.jsonl',pairs),('sequences.jsonl',sequences),
                       ('sources.jsonl',source_rows),('solver_audit.jsonl',reports)]:
        (out/name).write_text(''.join(json.dumps(t,ensure_ascii=False)+'\n' for t in rows))
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.out),ensure_ascii=False,indent=2))
