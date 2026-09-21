"""Build the decision-sufficient native-semantic B/P diagnostic (CPU only).

v5 supplied a semantic B judgment to P but left the evidential history in the
planning prompt.  That allowed P to reconstruct or override B.  v6 preserves
the native B and end-to-end interfaces, while giving both controlled P calls a
history-free prompt.  Every retained case additionally has an exact certificate
that all posteriors compatible with its semantic B share the same optimal-action
set.
"""
from collections import Counter, defaultdict
from copy import deepcopy
from pathlib import Path
import hashlib
import json
import sys


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from new.diagnostic_v4.build import base_task, occupied_geometries, requests_for
from new.diagnostic_v5.build import semantic_case
from new.diagnostic_v6.candidates import matched_candidate
from new.diagnostic_v6.semantic_sufficiency import certify


VERSION = 'bp-structure-diagnostic-v6-semantic-sufficient'
SELECTED = {
    'binary': (20358, 20796, 20838, 20908, 20966, 21030, 21350, 21598),
    'linear': (12073, 12231, 12921, 13027, 20241, 20469, 23037, 26565),
}

REFERENCE_POLICY_NOTE = (
    'For this diagnostic, voluntary choices follow the selected fixed policy. '
    'After any preset events, initialize every legal choice uniformly and '
    'synchronously update player best responses until the full policy is stable. '
    'Randomize uniformly among remaining optimal choices. This specifies the '
    'reference policy; it does not assert uniqueness. Preset events were required '
    'and do not provide evidence of the acting player\'s preferences.\n')

CLEAN_CONTINUATION_NOTE = (
    'For this diagnostic, other players follow one fixed continuation policy. '
    'Initialize every legal continuation choice uniformly and synchronously '
    'update player best responses until the full policy is stable; randomize '
    'uniformly among remaining optimal choices. This continuation policy is '
    'fixed before the supplied partner judgment and is not recomputed when that '
    'judgment changes.\n')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stable(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'))


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def clean_planning_request(request):
    """Remove every behavioral observation while retaining the decision state."""
    request = deepcopy(request)
    text = request['messages'][1]['content']
    old_objective = (
        'Infer the relevant preferences from the visible information and choose '
        'your next action.')
    new_objective = (
        'Choose your next action using the supplied partner judgment and the '
        'current game state.')
    if text.count(old_objective) != 1:
        raise ValueError('Unexpected P objective')
    text = text.replace(old_objective, new_objective)

    start = '\nEVENTS IN ORDER\n'
    end = '\nCURRENT BINDING STATE\n'
    if text.count(start) != 1 or text.count(end) != 1:
        raise ValueError('Unexpected chronology layout')
    before, remainder = text.split(start, 1)
    _, after = remainder.split(end, 1)
    text = before + end + after

    if text.count(REFERENCE_POLICY_NOTE) != 1:
        raise ValueError('Unexpected diagnostic policy note')
    text = text.replace(REFERENCE_POLICY_NOTE, CLEAN_CONTINUATION_NOTE)
    text = text.replace(
        'Your own preferences, known facts and observed choices can change your '
        'current belief.',
        'The supplied partner judgment is the complete inference output for this '
        'decision.')
    request['messages'][1]['content'] = text
    return request


def native_case(candidate, provenance, assisted):
    base = base_task(candidate, provenance)
    case = dict(
        id=base['id'], structure_id=base['structure_id'],
        structure_family=base['structure_family'], mode=base['mode'],
        provenance=provenance, coverage=base['coverage'], task=base,
        gold_belief=(candidate['posterior'] if provenance == 'voluntary'
                     else candidate['prior']).tolist(),
        planning_assisted_B=assisted and provenance == 'voluntary',
        likelihood_by_preference=(candidate['likelihood_by_preference']
                                  if provenance == 'voluntary'
                                  else [1., 1., 1.]),
        requests=requests_for(base))
    return semantic_case(case)


def certificate_summary(certificate):
    keys = ('method', 'semantic_region', 'decision_sufficient',
            'invariant_optimal_action_indices',
            'distinct_vertex_optimal_action_sets',
            'worst_exact_optimality_gap')
    return {key: deepcopy(certificate[key]) for key in keys}


def selected_candidates():
    occupied, protected_sources = occupied_geometries()
    result = []
    used = set()
    for mode in ('binary', 'linear'):
        for seed in SELECTED[mode]:
            candidate = matched_candidate(seed, mode, occupied)
            if candidate is None:
                raise RuntimeError(f'Frozen candidate is no longer reproducible: {mode}-{seed}')
            if candidate['family'] in used:
                raise RuntimeError('Selected structure geometry is duplicated')
            used.add(candidate['family'])
            result.append(candidate)
    return result, protected_sources


def build():
    candidates, protected_sources = selected_candidates()
    assisted = set()
    for mode in ('binary', 'linear'):
        rows = [candidate for candidate in candidates if candidate['mode'] == mode]
        rows.sort(key=lambda candidate: hashlib.sha256(
            f'assisted:{VERSION}:{candidate["seed"]}'.encode()).hexdigest())
        assisted.update(f'{candidate["mode"]}-{candidate["seed"]}'
                        for candidate in rows[:4])

    cases = []
    certificates = []
    for candidate in candidates:
        pair = [native_case(candidate, provenance,
                            f'{candidate["mode"]}-{candidate["seed"]}' in assisted)
                for provenance in ('voluntary', 'preset')]
        semantic_certificates = {}
        for case in pair:
            semantic_certificate = certify(
                case['gold_judgment'],
                case['task']['teacher']['per_world_payoffs'])
            if not semantic_certificate['decision_sufficient']:
                raise RuntimeError('Selected semantic summary is ambiguous: ' + case['id'])
            semantic_certificates[case['provenance']] = semantic_certificate
            case['semantic_decision_certificate'] = certificate_summary(
                semantic_certificate)
            case['coverage'] = sorted(set(case['coverage']) | {
                'semantic_decision_sufficient'})
            cases.append(case)
        left = set(semantic_certificates['voluntary'][
            'invariant_optimal_action_indices'])
        right = set(semantic_certificates['preset'][
            'invariant_optimal_action_indices'])
        if left & right:
            raise RuntimeError('Matched semantic optima overlap')
        certificates.append(dict(
            structure_id=pair[0]['structure_id'], seed=candidate['seed'],
            mode=candidate['mode'], structure_family=candidate['family'],
            same_physical_state=True, same_legal_actions=True,
            same_per_world_payoffs=True,
            semantic_judgments={case['provenance']: case['gold_judgment']
                                for case in pair},
            exact_teacher_posteriors={case['provenance']: case['teacher_posterior']
                                      for case in pair},
            semantic_decision_sufficiency=semantic_certificates,
            invariant_optimal_sets_disjoint=True,
            scope=(
                'Exact rational vertex enumeration certifies a common exact '
                'optimal-action set over the closed semantic posterior region. '
                'Exact posteriors remain backend-only.')))

    grouped = defaultdict(list)
    for case in cases:
        grouped[case['structure_id']].append(case)

    for structure_id, pair in grouped.items():
        if {case['provenance'] for case in pair} != {'voluntary', 'preset'}:
            raise ValueError('Incomplete pair: ' + structure_id)
        clean = [clean_planning_request(case['requests']['P_infer']) for case in pair]
        if stable(clean[0]) != stable(clean[1]):
            raise ValueError('Clean planning contexts differ: ' + structure_id)
        for case in pair:
            case['requests'] = {
                'B': case['requests']['B'],
                'P_clean': deepcopy(clean[0]),
                'P_infer': case['requests']['P_infer'],
            }
            case['coverage'] = sorted(set(case['coverage']) | {
                'history_free_controlled_P', 'state_sufficient_controlled_P'})

    cases.sort(key=lambda case: (case['mode'], case['structure_id'],
                                 0 if case['provenance'] == 'voluntary' else 1))
    if len(cases) != 32 or len(grouped) != 16:
        raise ValueError('Expected 16 structures and 32 cases')
    if Counter(case['mode'] for case in cases) != {'binary': 16, 'linear': 16}:
        raise ValueError('Expected balanced game modes')

    selection = dict(
        version=VERSION, selected_structures=16,
        modes=dict(Counter(candidate['mode'] for candidate in candidates)),
        selected={mode: list(seeds) for mode, seeds in SELECTED.items()},
        protected_sources=protected_sources,
        rule=(
            'Teacher-only deterministic selection. Retain a matched structure '
            'only when exact rational polytope certificates prove that every '
            'posterior compatible with each native semantic judgment has the '
            'same exact optimal-action set, and the two invariant sets are '
            'disjoint. No learner output enters selection.'),
        planning_intervention=(
            'Controlled P receives current physical state and a supplied semantic '
            'judgment, but no behavioral chronology or provenance metadata.'),
        planning_assisted_B_structures=sorted(assisted))

    write_json(HERE / 'cases.json', cases)
    write_json(HERE / 'certificates.json', certificates)
    write_json(HERE / 'selection.json', selection)
    dependencies = [
        Path(__file__), HERE / 'candidates.py', HERE / 'semantic_sufficiency.py',
        ROOT / 'new/diagnostic_v4/build.py',
        ROOT / 'new/diagnostic_v5/build.py',
        ROOT / 'training/b_sft/preference_contract.py']
    manifest = dict(
        version=VERSION, split='frozen_structure_test', structures=16,
        matched_cases=32,
        default_repeats=3, max_model_calls_per_model=(32 * 4 + 8) * 3,
        conditions=['B', 'B_with_qualitative_partner_plan',
                    'model_B_model_P', 'correct_B_model_P', 'end_to_end_P'],
        controlled_P_contract={
            'included': ['game rules', 'goal requirements', 'known preferences',
                         'current commitments', 'remaining turns',
                         'investigation quota', 'legal actions',
                         'fixed partner policy', 'supplied semantic judgment'],
            'excluded': ['behavioral chronology', 'voluntary/preset provenance',
                         'case metadata', 'numeric posterior', 'per-world payoff'],
            'pair_invariant': (
                'Before judgment insertion, voluntary and preset controlled-P '
                'requests are byte-identical within each structure.')},
        model_facing_belief_contract=['possible_preferences', 'favored'],
        belief_scope=(
            'Correct semantic B is the deployed summary, not a numeric posterior. '
            'Every retained case is certified decision-sufficient: its complete '
            'compatible posterior region has one invariant exact optimal-action set.'),
        semantic_sufficiency={
            'method': 'exact-rational-polytope-vertices-v1',
            'certified_cases': 32,
            'certified_matched_structures': 16,
            'matched_invariant_optimal_sets_disjoint': 16,
            'boundary_policy': (
                'Certify the closed semantic region, a conservative superset of '
                'posteriors serialized by the strict support/favored rules.')},
        scoring=(
            'Exact teacher posterior and per-world payoffs are backend-only. '
            'End-to-end P retains the original history; controlled P does not.'),
        files={name: sha(HERE / name) for name in
               ('cases.json', 'certificates.json', 'selection.json')},
        dependencies={str(path.relative_to(ROOT)): sha(path)
                      for path in dependencies})
    write_json(HERE / 'manifest.json', manifest)
    print(json.dumps(dict(structures=16, cases=32,
                          calls=manifest['max_model_calls_per_model'],
                          version=VERSION), indent=2))


if __name__ == '__main__':
    build()
