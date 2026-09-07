import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from benac_p.functional_dependency import sensitivity, readiness, build
from benac_p.endgame_diagnose import Fixture, main

FIXTURES = Path(__file__).resolve().parents[3]/'examples/benac_p/fixtures/functional_dependency.json'


def test_sensitivity_requires_action_cost_not_just_shifted_utilities():
    assert sensitivity([(['want'], [1., 0.]), (['avoid'], [2., 1.])]) is None
    # One shared optimal action does not erase the cost of another action that
    # is only optimal under the first type. We never demand an action switch.
    proof = sensitivity([(['want'], [1., 1.]), (['avoid'], [0., 1.])])
    assert proof['right_regret'] == 1.
    assert proof['action_indices'] == [0, 1]


def test_readiness_requires_both_directions_and_distinct_source_games():
    certs = {str(i):dict(bundle='same', split='discovery', groups=['b_to_p','p_to_b']) for i in range(4)}
    r = readiness(SimpleNamespace(certificates=certs), 3)
    assert not r['passed']
    assert r['independent_games']['discovery/b_to_p'] == 1
    assert r['independent_games']['confirmation/p_to_b'] == 0


def test_frozen_set_and_forced_pairs_preserve_native_actions_and_history(monkeypatch):
    from benac_p import dependency_certificate
    def forbidden(*args, **kwargs):
        raise AssertionError('Functional diagnosis must not call the strict certificate.')
    monkeypatch.setattr(dependency_certificate, 'certify', forbidden)
    raw = json.loads(FIXTURES.read_text())
    suite = build([Fixture(r) for r in raw['fixtures']])
    assert readiness(suite, 3)['passed']
    for fid, c in suite.certificates.items():
        f = suite.fixtures[fid]
        q = suite.cases[fid+'/root']['q']
        oracle = suite.arms[fid]['oracle']['action']
        assert next(v for a, v in q if a.to_dict()==oracle) == max(v for _, v in q)
        if 'p_to_b' not in c['groups']:
            continue
        assert c['functional']['planning_to_belief']['information_gap'] > 0
        for arm in ('low_information', 'high_information'):
            branches = suite.arms[fid][arm]['branches']
            assert sum(b['weight'] for b in branches) == pytest.approx(1)
            for branch in branches:
                case = suite.cases[branch['case']]
                assert not case['node'].state.is_terminal
                tasks = [t for t in suite.tasks if t['id']==branch['case']+'/plan_oracle']
                assert tasks[0]['input']['history'] == f.history_text(case['node'])
                assert len(tasks[0]['input']['legal_actions']) == len(f.search.actions(case['node']))


def test_synthetic_forced_contrast_distinguishes_uncertainty_from_update_error(tmp_path):
    args = ['--functional-dependency', '--fixtures', str(FIXTURES), '--min-games-per-condition', '3',
            '--output-dir', str(tmp_path/'run'), '--oracle-check']
    main(args)
    scores = json.loads((tmp_path/'run/scores.json').read_text())
    assert all(r['belief_exact']==1 and r.get('OL',0)==0 and r.get('LL',0)==0 for r in scores['cases'])
    pairs = [r for r in scores['active'] if 'forced_information_gap' in r]
    assert len(pairs) == 6
    for r in pairs:
        assert r['forced_information_gap'] > 0
        assert r['forced_low_belief_exact'] == r['forced_high_belief_exact'] == 1
        assert r['forced_belief_exact_delta'] == 0  # Uninformative evidence is not an updater error.
    main(args+['--score-only'])
    assert json.loads((tmp_path/'run/scores.json').read_text()) == scores
