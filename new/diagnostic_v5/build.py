"""Build the native-semantic structure diagnostic (CPU only).

This revision keeps exact posteriors strictly teacher-side.  Model-facing B
outputs and B->P interventions use only the deployed
``possible_preferences``/``favored`` contract.
"""
from copy import deepcopy
from pathlib import Path
from collections import Counter
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from new.diagnostic_v4.build import (base_task, matched_candidate,
    occupied_geometries, requests_for)

VERSION = 'bp-structure-diagnostic-v5-native-semantic'
REPLACED_STRUCTURE = 'linear-12647'
REPLACEMENT_SEED = 13001


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def replacement_cases():
    occupied, _ = occupied_geometries()
    candidate = matched_candidate(REPLACEMENT_SEED, 'linear', occupied)
    if candidate is None:
        raise RuntimeError('Frozen replacement candidate is no longer reproducible')
    result = []
    for provenance in ('voluntary', 'preset'):
        base = base_task(candidate, provenance)
        result.append(dict(
            id=base['id'], structure_id=base['structure_id'],
            structure_family=base['structure_family'], mode=base['mode'],
            provenance=provenance, coverage=base['coverage'], task=base,
            gold_belief=(candidate['posterior'] if provenance == 'voluntary'
                         else candidate['prior']).tolist(),
            planning_assisted_B=False,
            likelihood_by_preference=(candidate['likelihood_by_preference']
                                      if provenance == 'voluntary' else [1., 1., 1.]),
            requests=requests_for(base)))
    return result


def semantic_case(case):
    """Remove every exact distribution from the model-facing case payload."""
    case = deepcopy(case)
    case['teacher_posterior'] = case.pop('gold_belief')
    case['gold_judgment'] = deepcopy(case['task']['teacher']['gold'])
    supplied = case['task']['input'].get('supplied_belief', {})
    supplied.pop('joint_distribution', None)
    supplied['support'] = ('The inference stage supplies possible_preferences '
                           'and favored; no probability is supplied to the planner.')
    case['task']['input']['supplied_belief'] = supplied
    # P_gold contains an exact posterior by construction and is deliberately
    # discarded.  P_infer is the native history-to-action request from which
    # the runner makes semantic interventions.
    case['requests'] = {
        'B': case['requests']['B'],
        'P_infer': case['requests']['P_infer'],
    }
    case['coverage'] = sorted(set(case['coverage']) | {
        'native_semantic_B', 'semantic_B_to_P_intervention'})
    return case


def build():
    old_path = ROOT / 'new/diagnostic_v4/cases.json'
    old = [case for case in json.loads(old_path.read_text())
           if case['structure_id'] != REPLACED_STRUCTURE]
    raw = old + replacement_cases()
    cases = [semantic_case(case) for case in raw]
    cases.sort(key=lambda c: (c['mode'], c['structure_id'],
                              0 if c['provenance'] == 'voluntary' else 1))

    by_structure = {}
    for case in cases:
        by_structure.setdefault(case['structure_id'], []).append(case)
    if len(by_structure) != 16 or len(cases) != 32:
        raise ValueError('Expected 16 matched structures and 32 cases')
    if len({c['structure_family'] for c in cases}) != 16:
        raise ValueError('Canonical structure geometries must be independent')
    if Counter(c['mode'] for c in cases) != {'binary': 16, 'linear': 16}:
        raise ValueError('Expected eight structures per game mode')
    for pair in by_structure.values():
        if {c['provenance'] for c in pair} != {'voluntary', 'preset'}:
            raise ValueError('Missing matched provenance')
        if pair[0]['gold_judgment'] == pair[1]['gold_judgment']:
            raise ValueError('Semantic B is identical across a dependency pair')
        if pair[0]['task']['input']['current_state'] != pair[1]['task']['input']['current_state']:
            raise ValueError('Physical state changed across a pair')
        if pair[0]['task']['input']['legal_actions'] != pair[1]['task']['input']['legal_actions']:
            raise ValueError('Legal actions changed across a pair')
        if pair[0]['task']['teacher']['per_world_payoffs'] != pair[1]['task']['teacher']['per_world_payoffs']:
            raise ValueError('Per-world payoff table changed across a pair')

    certificates = [dict(
        structure_id=sid,
        mode=pair[0]['mode'],
        structure_family=pair[0]['structure_family'],
        same_physical_state=True,
        same_legal_actions=True,
        same_per_world_payoffs=True,
        semantic_judgments={c['provenance']: c['gold_judgment'] for c in pair},
        exact_teacher_posteriors={c['provenance']: c['teacher_posterior'] for c in pair},
        scope=('Exact posteriors are retained only for local scoring. They are '
               'never serialized into a model request.'))
        for sid, pair in sorted(by_structure.items())]
    selection = dict(
        version=VERSION, selected_structures=16,
        modes=dict(Counter(c['mode'] for c in cases)),
        source='Fifteen v4 geometries plus one teacher-only replacement search.',
        replaced_structure=REPLACED_STRUCTURE,
        replacement_structure=f'linear-{REPLACEMENT_SEED}',
        rule=('Require different native semantic B labels across each matched '
              'voluntary/preset pair; no learner output enters selection.'),
        planning_assisted_B_structures=sorted({c['structure_id'] for c in cases
                                               if c['planning_assisted_B']}))

    write_json(HERE / 'cases.json', cases)
    write_json(HERE / 'certificates.json', certificates)
    write_json(HERE / 'selection.json', selection)
    dependencies = [Path(__file__), old_path,
                    ROOT / 'new/diagnostic_v4/build.py',
                    ROOT / 'training/b_sft/preference_contract.py']
    manifest = dict(
        version=VERSION, split='frozen_structure_test', structures=16,
        matched_cases=32, default_repeats=3,
        max_model_calls_per_model=(32 * 4 + 8) * 3,
        conditions=['B', 'B_with_qualitative_partner_plan',
                    'model_B_model_P', 'correct_B_model_P', 'end_to_end_P'],
        model_facing_belief_contract=['possible_preferences', 'favored'],
        forbidden_model_facing_fields=['posterior', 'probability',
                                       'joint_distribution', 'preference_weights'],
        scoring=('Exact teacher posterior and per-world payoffs are backend-only. '
                 'No reference-P cell is computed from a model semantic judgment.'),
        files={name: sha(HERE / name) for name in
               ('cases.json', 'certificates.json', 'selection.json')},
        dependencies={str(path.relative_to(ROOT)): sha(path)
                      for path in dependencies})
    write_json(HERE / 'manifest.json', manifest)
    print(json.dumps(dict(structures=16, cases=32,
                          calls=manifest['max_model_calls_per_model'],
                          selection=selection), indent=2))


if __name__ == '__main__':
    build()
