"""Build the clean-state native-semantic B/P diagnostic (CPU only).

v5 supplied a semantic B judgment to P but left the evidential history in the
planning prompt.  That allowed P to reconstruct or override B.  v6 preserves
the v5 B and end-to-end requests, while giving both controlled P calls a
history-free, state-sufficient prompt that is byte-identical across the
voluntary/preset pair before the supplied judgment is inserted.
"""
from collections import Counter, defaultdict
from copy import deepcopy
from pathlib import Path
import hashlib
import json


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
V5 = ROOT / 'new/diagnostic_v5'
VERSION = 'bp-structure-diagnostic-v6-clean-planning-state'

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


def load_v5():
    manifest = json.loads((V5 / 'manifest.json').read_text())
    for name, digest in manifest['files'].items():
        if sha(V5 / name) != digest:
            raise ValueError('Frozen v5 artifact changed: ' + name)
    return manifest, json.loads((V5 / 'cases.json').read_text())


def build():
    old_manifest, cases = load_v5()
    cases = deepcopy(cases)
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

    certificates = json.loads((V5 / 'certificates.json').read_text())
    selection = json.loads((V5 / 'selection.json').read_text())
    selection = dict(selection,
        version=VERSION,
        planning_intervention=(
            'Controlled P receives current physical state and a supplied semantic '
            'judgment, but no behavioral chronology or provenance metadata.'),
        source_suite=old_manifest['version'])

    write_json(HERE / 'cases.json', cases)
    write_json(HERE / 'certificates.json', certificates)
    write_json(HERE / 'selection.json', selection)
    dependencies = [Path(__file__), V5 / 'manifest.json', V5 / 'cases.json']
    manifest = dict(
        version=VERSION, source_suite=old_manifest['version'],
        split='frozen_structure_test', structures=16, matched_cases=32,
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
