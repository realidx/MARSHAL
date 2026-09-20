"""Build the frozen, structure-level B/P diagnostic suite. CPU only.

Selection uses native teacher quantities and exact geometry identities only.  It
never calls or scores a language model.  Existing v2/v3 artifacts are inputs for
comparison, not files to mutate.
"""
from collections import Counter
from copy import copy, deepcopy
from fractions import Fraction
from pathlib import Path
import hashlib
import json
import random
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from training.b_sft.prepare_no_catalogue_probe import expand_support, view
from training.b_sft.preference_contract import belief, profile
from training.b_sft.social_bp_curriculum import acceptable
from training.b_sft.social_b_oracle import NAMES, canonical
from training.b_sft.social_private_teacher import PrivateEpisode, audit_native
from training.social_mixed.structure_coverage import geometry_id
from new.diagnostic_v2.composition.prepare import request


VERSION = 'bp-structure-diagnostic-v4'
VALUES = ('want', 'neutral', 'avoid')
NUMERIC = (1, 0, -1)
TARGET_STRUCTURES = 16
PER_MODE = 8
ASSISTED_STRUCTURES = 8
SEED_START = 12000
SEED_STOP = 20000
MIN_EVIDENCE_TV = .15
MIN_DECISION_GAP = .15
MIN_PATH_PROBABILITY = .02


def stable(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def mode_of(game):
    return 'binary' if all(g['binary'] for g in game['goals']) else 'linear'


def occupied_geometries():
    """Protect every active data split, final evaluation, and the v3 pilot."""
    occupied = set()
    sources = []
    data = ROOT / 'examples/social_mixed/data_reasoning_v6'
    for name in ('bp_train.jsonl', 'bp_validation.jsonl', 'bp_test.jsonl',
                 'selfplay_train.jsonl', 'selfplay_validation.jsonl'):
        path = data / name
        if not path.exists():
            continue
        sources.append(str(path.relative_to(ROOT)))
        for line in path.read_text().splitlines():
            row = json.loads(line)
            game = row.get('input', row.get('raw'))['game']
            occupied.add(geometry_id(game))
    final = ROOT / 'examples/final_evaluation/benac_a_v1/resets.jsonl'
    if final.exists():
        sources.append(str(final.relative_to(ROOT)))
        for line in final.read_text().splitlines():
            occupied.add(geometry_id(json.loads(line)['raw']['game']))
    pilot = HERE.parent / 'diagnostic_v3/cases.json'
    if pilot.exists():
        sources.append(str(pilot.relative_to(ROOT)))
        for case in json.loads(pilot.read_text()):
            occupied.add(geometry_id(case['task']['input']['game']))
    return occupied, sources


def candidate_raw(seed, mode):
    """Fresh two-player geometry with exactly one unknown partner preference."""
    rng = random.Random(seed)
    if mode == 'binary':
        # A certified tradeoff motif (two alternative joint commitments plus a
        # hidden-preference goal), embedded in fresh topologies.  Extra goals
        # and optional third commitments change the canonical dependency graph;
        # the later search still admits a structure only if its full re-solved
        # teacher satisfies every posterior/action-gap criterion.
        counts = [rng.choice((2, 3)), rng.choice((2, 3))]
        goals = rng.choice((4, 5, 6, 7))
        target = 2
        own = [1, 1, 1] + [rng.choice((1, 0, -1)) for _ in range(goals - 3)]
        partner = [1, 0, 0] + [1 for _ in range(goals - 3)]
        pairs = [(1, 0), (1, 1), (0, 0)]
        for extra in range(goals - 3):
            if extra == 0 and counts[0] == 3:
                left = 2
            else:
                left = rng.randrange(counts[0])
            if extra == 1 and counts[1] == 3:
                right = 2
            else:
                right = rng.randrange(counts[1])
            pairs.append((left, right))
    else:
        counts = [2, 2]
        goals = rng.choice((3, 4, 5, 6))
        target = rng.randrange(goals)
        own = [rng.choice((1, 1, 0, -1)) for _ in range(goals)]
        own[target] = 1  # keeps all three target values generator-valid
        partner = [rng.choice((1, 0, -1)) for _ in range(goals)]
        anchor = next(g for g in range(goals) if g != target)
        partner[anchor] = 1
        for g in range(goals):
            if g != target and own[g] == 0 and partner[g] == 0:
                partner[g] = 1
        pairs = [(rng.randrange(counts[0]), rng.randrange(counts[1])) for _ in range(goals)]
    rows = []
    for value in NUMERIC:
        row = partner.copy(); row[target] = value; rows.append(row)
    requirements = []
    for goal, (left, right) in enumerate(pairs):
        requirements.append(dict(goal_id=goal, binary=mode == 'binary', required_actions=[
            dict(player_id=0, action_id=left),
            dict(player_id=1, action_id=right)]))
    raw = dict(id=f'diagnostic-v4-{mode}-{seed}', ego=0, own_preferences=own,
        history=[], type_catalogues={'0': [own], '1': rows},
        game=dict(n_players=2, n_actions_per_player=counts, max_changes=1,
            menu_enabled=False, round_robin=[1, 0], goals=requirements))
    raw['background_prior'] = profile('balanced')
    raw, public, expansion = expand_support(raw)
    if expansion['unknown_slots'] != [(1, target)]:
        return None
    return raw, public, target


def posterior_vector(episode, own, target):
    b = episode.belief(1, target, observer=0, own=own)['preference_weights']
    return np.array([b[k] for k in VALUES], dtype=float)


def exact_best(values):
    best = float(np.max(values))
    return {i for i, v in enumerate(values) if abs(float(v) - best) < 1e-9}


def decision_gap(values):
    values = np.asarray(values, dtype=float)
    best = float(values.max())
    lower = values[best - values > 1e-9]
    return None if not len(lower) else best - float(lower.max())


def focal_positions(root, own):
    """Enumerate positive-probability public paths to the final focal proposal."""
    frontier = [(root, [], 1.)]
    found = []
    for _ in range(4):
        nxt = []
        for episode, events, path_probability in frontier:
            entry = episode.tree.entries[episode.index]
            state = entry.node.state.public_state()
            if entry.actor == 0 and entry.node.pending is None and state['turn_index'] == len(state['round_robin']) - 1:
                found.append((episode, events, path_probability))
                continue
            if entry.actor is None:
                continue
            weights = episode._weights(0, own, ())
            for ai, action in enumerate(entry.actions):
                event = action.to_dict()
                # Public query targets do not reveal the private answer to the
                # focal player and are not needed in this B->P slice.
                if event.get('action') == 'INVESTIGATE':
                    continue
                probability = float(weights @ episode.tree.policy[episode.index][ai])
                if probability <= 0:
                    continue
                child = copy(episode); child.weights = episode.weights.copy()
                try:
                    child.observe(event)
                except ValueError:
                    continue
                nxt.append((child, events + [event], path_probability * probability))
        frontier = nxt
    return found


def path_likelihoods(raw, events, target):
    """Likelihood of the displayed voluntary path under each target value."""
    episode = PrivateEpisode(raw, [], seconds=30, max_nodes=20000, max_sweeps=128)
    likelihood = np.ones(len(episode.tree.worlds), dtype=float)
    for event in events:
        entry = episode.tree.entries[episode.index]
        lookup = {canonical(a.to_dict()): i for i, a in enumerate(entry.actions)}
        ai = lookup[canonical(event)]
        # The observer's own response is part of the physical path but is not
        # evidence about the partner.  Its information-set policy is constant
        # over the compatible partner types and therefore cancels in Bayes.
        if entry.actor != 0:
            likelihood *= episode.tree.policy[episode.index][ai]
        episode.observe(event)
    result = []
    for value in NUMERIC:
        ids = [i for i, world in enumerate(episode.tree.worlds) if world[1][target] == value]
        if len(ids) != 1:
            raise ValueError('Expected exactly one world per queried preference')
        result.append(float(likelihood[ids[0]]))
    return result


def matched_candidate(seed, mode, occupied):
    built = candidate_raw(seed, mode)
    if built is None:
        return None
    raw, public, target = built
    family = geometry_id(raw['game'])
    if family in occupied:
        return None
    own = raw['own_preferences']
    root = PrivateEpisode(raw, [], seconds=30, max_nodes=20000, max_sweeps=128)
    prior = posterior_vector(root, own, target)
    if not np.allclose(prior, [1/3] * 3, atol=1e-9, rtol=0):
        return None
    options = []
    for episode, events, path_probability in focal_positions(root, own):
        if path_probability < MIN_PATH_PROBABILITY:
            continue
        posterior = posterior_vector(episode, own, target)
        tv = float(np.abs(posterior - prior).sum() / 2)
        if tv < MIN_EVIDENCE_TV:
            continue
        entry = episode.tree.entries[episode.index]
        actions = [a.to_dict() for a in entry.actions]
        pay = np.array([episode.tree.values[c] for c in entry.children])
        post_all_values = np.einsum('awp,w->ap', pay, episode._weights(0, own, ()))
        prior_all_values = np.einsum('awp,w->ap', pay, root._weights(0, own, ()))
        post_values = post_all_values[:, 0]
        prior_values = prior_all_values[:, 0]
        post_best, prior_best = exact_best(post_values), exact_best(prior_values)
        post_gap, prior_gap = decision_gap(post_values), decision_gap(prior_values)
        if post_best & prior_best or post_gap is None or prior_gap is None:
            continue
        if min(post_gap, prior_gap) < MIN_DECISION_GAP:
            continue
        preset = PrivateEpisode(raw, events, seconds=30, max_nodes=20000, max_sweeps=128)
        pe = preset.tree.entries[preset.index]
        preset_actions = [a.to_dict() for a in pe.actions]
        preset_pay = np.array([preset.tree.values[c] for c in pe.children])
        if (entry.node.state.public_state() != pe.node.state.public_state() or
                actions != preset_actions or not np.allclose(pay, preset_pay, atol=1e-9, rtol=0)):
            continue
        lead = VALUES[int(np.argmax(posterior))]
        signature = stable([events, sorted(post_best), sorted(prior_best)])
        likelihood = path_likelihoods(raw, events, target)
        implied = prior * np.asarray(likelihood)
        implied /= implied.sum()
        if not np.allclose(implied, posterior, atol=1e-9, rtol=0):
            raise ValueError('Saved behavior likelihood does not reproduce posterior')
        options.append(dict(seed=seed, mode=mode, family=family, raw=raw, public=public,
            target=target, events=events, voluntary=episode, preset=preset,
            prior=prior, posterior=posterior, actions=actions, pay=pay,
            post_values=post_values, prior_values=prior_values,
            post_all_values=post_all_values, prior_all_values=prior_all_values, post_gap=post_gap,
            prior_gap=prior_gap, evidence_tv=tv, path_probability=path_probability,
            posterior_leader=lead, signature=signature,
            likelihood_by_preference=likelihood))
    if not options:
        return None
    # Predetermine a preferred posterior direction from the seed.  This avoids
    # letting the largest available avoid-signal dominate every geometry while
    # remaining wholly independent of learner outputs.
    preferred = VALUES[(seed // 2) % len(VALUES)]
    directed = [x for x in options if x['posterior_leader'] == preferred]
    pool = directed or options
    return min(pool, key=lambda x: (-min(x['post_gap'], x['prior_gap']),
                                    -x['evidence_tv'], x['signature']))


def fractions(weights):
    result = []
    for value, weight in zip(NUMERIC, weights):
        if weight <= 0:
            continue
        rational = Fraction(float(weight)).limit_denominator(1_000_000)
        if abs(float(rational) - float(weight)) > 1e-10:
            raise ValueError('Posterior is not stably serializable')
        result.append((value, str(rational)))
    if sum(Fraction(p) for _, p in result) != 1:
        raise ValueError('Posterior fractions do not sum to one')
    return result


def base_task(candidate, provenance):
    episode = candidate[provenance]
    weights = candidate['posterior'] if provenance == 'voluntary' else candidate['prior']
    setup = [] if provenance == 'voluntary' else candidate['events']
    events = candidate['events'] if provenance == 'voluntary' else []
    inp = view(episode, candidate['public'], 0, candidate['raw']['own_preferences'], [], setup, events)
    inp.update(background_prior=profile('balanced'), favored_margin=.1,
        legal_actions=candidate['actions'], queries=[dict(player=1, goal=candidate['target'])],
        supplied_belief=dict(known_preferences=deepcopy(candidate['public']),
            unresolved_preferences=[dict(player=1, goal=candidate['target'])],
            support='This is YOUR supplied exact joint distribution. Derived from the displayed history.',
            joint_distribution=[dict(probability=p, preferences=[dict(player=1, goal=candidate['target'], preference=NAMES[v])])
                                for v, p in fractions(weights)]))
    gold_weights = dict(zip(VALUES, map(float, weights)))
    teacher = dict(gold=belief(gold_weights), preference_weights=gold_weights,
        acceptable_actions=[candidate['actions'][i] for i in acceptable(
            candidate['post_all_values'] if provenance == 'voluntary' else candidate['prior_all_values'],
            0, actions=candidate['actions'])],
        action_values=np.einsum('awp,w->ap', candidate['pay'], weights).tolist(),
        per_world_payoffs=candidate['pay'].tolist(), worlds=episode.tree.worlds,
        own_tolerance=.1, social_tolerance=.1,
        policy_sha256=episode.tree.certificate['policy_sha256'])
    case_id = f"{candidate['mode']}-{candidate['seed']}:{provenance}"
    coverage = ['B1/formation', 'P2/belief_conditioned', 'P3/final_turn_opportunity_cost',
                'voluntary_vs_preset', 'four_cell_repair']
    if np.count_nonzero(weights) < 3:
        coverage.append('support_elimination')
    else:
        coverage.append('probability_shift')
    return dict(id=case_id, structure_id=f"{candidate['mode']}-{candidate['seed']}",
        structure_family=candidate['family'], mode=candidate['mode'], provenance=provenance,
        split='frozen_structure_test', condition=None, task='P', skill='history_planning',
        coverage=coverage, input=inp, teacher=teacher)


def requests_for(base):
    result = {}
    for condition in ('B', 'P_gold', 'P_infer'):
        task = deepcopy(base)
        task.update(id=base['id'] + ':' + condition, condition=condition,
                    task='B' if condition == 'B' else 'P',
                    skill='formation' if condition == 'B' else 'history_planning')
        result[condition] = request(task)
    return result


def choose_candidates(candidates):
    """Balance mode and posterior direction without learner-dependent selection."""
    chosen = []
    used = set()
    for mode in ('binary', 'linear'):
        pool = [c for c in candidates if c['mode'] == mode]
        by_leader = {v: [c for c in pool if c['posterior_leader'] == v] for v in VALUES}
        for rows in by_leader.values():
            rows.sort(key=lambda c: hashlib.sha256(f"{VERSION}:{c['seed']}:{c['signature']}".encode()).hexdigest())
        # Round-robin leaders first; fill from the stable union if a cell is sparse.
        while sum(c['mode'] == mode for c in chosen) < PER_MODE:
            progressed = False
            for leader in VALUES:
                rows = by_leader[leader]
                while rows and rows[0]['family'] in used:
                    rows.pop(0)
                if rows and sum(c['mode'] == mode for c in chosen) < PER_MODE:
                    c = rows.pop(0); chosen.append(c); used.add(c['family']); progressed = True
            if not progressed:
                break
        if sum(c['mode'] == mode for c in chosen) != PER_MODE:
            raise RuntimeError(f'Not enough certified {mode} structures')
    return chosen


def choose_assisted(chosen):
    selected = []
    for mode in ('binary', 'linear'):
        rows = [c for c in chosen if c['mode'] == mode]
        rows.sort(key=lambda c: hashlib.sha256(f"assisted:{VERSION}:{c['seed']}".encode()).hexdigest())
        selected.extend(rows[:ASSISTED_STRUCTURES // 2])
    if len(selected) != ASSISTED_STRUCTURES:
        raise RuntimeError('Unable to balance planning-assisted B structures')
    return {f"{c['mode']}-{c['seed']}" for c in selected}


def build():
    occupied, protected_sources = occupied_geometries()
    candidates = []
    failures = Counter()
    seen = set(occupied)
    for seed in range(SEED_START, SEED_STOP):
        # Assign a seed to only one scoring mode so binary/linear are independent.
        mode = 'binary' if seed % 2 == 0 else 'linear'
        try:
            candidate = matched_candidate(seed, mode, seen)
        except Exception as exc:
            failures[type(exc).__name__] += 1
            continue
        if candidate is None:
            failures['ineligible'] += 1
            continue
        candidates.append(candidate); seen.add(candidate['family'])
        if seed % 100 == 99:
            print(json.dumps(dict(seed=seed, eligible=dict(Counter(c['mode'] for c in candidates)))), flush=True)
        if sum(c['mode'] == 'binary' for c in candidates) >= PER_MODE and sum(c['mode'] == 'linear' for c in candidates) >= PER_MODE:
            break
    chosen = choose_candidates(candidates)
    assisted = choose_assisted(chosen)
    cases = []
    certificates = []
    for c in chosen:
        for provenance in ('voluntary', 'preset'):
            base = base_task(c, provenance)
            cases.append(dict(id=base['id'], structure_id=base['structure_id'],
                structure_family=base['structure_family'], mode=base['mode'], provenance=provenance,
                coverage=base['coverage'], task=base,
                gold_belief=(c['posterior'] if provenance == 'voluntary' else c['prior']).tolist(),
                planning_assisted_B=base['structure_id'] in assisted and provenance == 'voluntary',
                likelihood_by_preference=c['likelihood_by_preference'] if provenance == 'voluntary' else [1., 1., 1.],
                requests=requests_for(base)))
        certificates.append(dict(structure_id=f"{c['mode']}-{c['seed']}", seed=c['seed'], mode=c['mode'],
            structure_family=c['family'], query=dict(player=1, goal=c['target']), events=c['events'],
            path_probability=c['path_probability'], evidence_total_variation=c['evidence_tv'],
            voluntary_posterior=c['posterior'].tolist(), preset_posterior=c['prior'].tolist(),
            voluntary_path_likelihood_by_preference=c['likelihood_by_preference'],
            voluntary_decision_gap=c['post_gap'], preset_decision_gap=c['prior_gap'],
            voluntary_exact_best=sorted(exact_best(c['post_values'])),
            preset_exact_best=sorted(exact_best(c['prior_values'])),
            physical_state=c['voluntary'].tree.entries[c['voluntary'].index].node.state.public_state(),
            legal_actions=c['actions'], per_world_payoffs=c['pay'].tolist(),
            voluntary_teacher=c['voluntary'].tree.certificate,
            preset_teacher=c['preset'].tree.certificate,
            native_transition_audit=audit_native(c['preset'].tree)))
    write_json(HERE / 'cases.json', cases)
    write_json(HERE / 'certificates.json', certificates)
    selection = dict(version=VERSION, seed_range=[SEED_START, seed], eligible_candidates=len(candidates),
        selected_structures=len(chosen), modes=dict(Counter(c['mode'] for c in chosen)),
        posterior_leaders=dict(Counter(c['posterior_leader'] for c in chosen)),
        planning_assisted_B_structures=sorted(assisted),
        rejected=dict(failures), protected_geometry_count=len(occupied), protected_sources=protected_sources,
        selected=[dict(structure_id=f"{c['mode']}-{c['seed']}", seed=c['seed'], mode=c['mode'],
                       structure_family=c['family'], posterior_leader=c['posterior_leader']) for c in chosen],
        rule='Teacher-only deterministic selection; no model responses exist or enter selection.')
    write_json(HERE / 'selection.json', selection)
    dependencies = [Path(__file__), ROOT/'training/b_sft/social_private_teacher.py',
        ROOT/'training/b_sft/prepare_no_catalogue_probe.py',
        ROOT/'training/social_mixed/structure_coverage.py',
        HERE.parent/'diagnostic_v2/composition/prepare.py']
    manifest = dict(version=VERSION, split='frozen_structure_test', structures=len(chosen),
        matched_cases=len(cases), planning_assisted_B_structures=len(assisted), default_repeats=3,
        default_model_calls_per_unassisted_structure=24,
        max_model_calls_per_model=(len(cases)*4 + len(assisted))*3,
        conditions=['B', 'B_with_planning_assistance', 'model_B_model_P',
                    'correct_B_model_P', 'end_to_end_P'],
        scoring='All decision utility uses the certified true posterior. Reference cells are offline exact expected-utility maximizers with uniform exact ties.',
        selection='Teacher-only, geometry-disjoint deterministic search; frozen before model calls.',
        files={name: sha(HERE/name) for name in ('cases.json', 'certificates.json', 'selection.json')},
        dependencies={str(p.relative_to(ROOT)): sha(p) for p in dependencies})
    write_json(HERE / 'manifest.json', manifest)
    print(json.dumps(dict(structures=len(chosen), cases=len(cases), assisted=len(assisted),
                          calls=manifest['max_model_calls_per_model'], selection=selection), indent=2))


if __name__ == '__main__':
    build()
