from copy import deepcopy
from dataclasses import replace
import math

import numpy as np
import pytest

from benac_p.b_corpus import chat, plan_sources, public_oracle, replay_public, select_pairs, structure_fingerprint
from benac_p.b_data_audit import audit_game
from benac_p.b_training_data import make_game
from benac_p.generator import GeneratorConfig, generate_game
from benac_p.mcts_oracle import Budget
from benac_p.schema import ActionRef, GameSpec, Goal
from benac_p.state import GameState
from benac_p.observations import build_player_observation


def test_linear_fraction_rewards_and_scaled_oracle():
    cfg = GeneratorConfig(n_players=3, actions_per_player=2, n_goals=6, n_rounds=1, linear_goal_fraction=.5)
    spec, oracle, actual, _, _ = make_game(76123, 'custom', Budget(simulations=32), 3, config=cfg)
    assert any(g.binary for g in spec.goals) and any(not g.binary for g in spec.goals)
    assert oracle.utility_scale == math.lcm(*(len(g.required_actions) for g in spec.goals if not g.binary))
    state = GameState(spec)
    # Exhaustively compare every public commitment mask, including partial and negative rewards.
    for mask in range(1 << oracle.bits):
        for p, n in enumerate(spec.n_actions_per_player):
            for a in range(n):
                state.commitments[p, a] = (mask >> (oracle.offsets[p]+a)) & 1
        expected = []
        for g in spec.goals:
            met = sum(state.commitments[a.player_id, a.action_id] for a in g.required_actions)
            expected.append(int(met == len(g.required_actions)) if g.binary else met/len(g.required_actions))
        np.testing.assert_allclose(state.goal_satisfaction(), expected)
        np.testing.assert_allclose(state.terminal_rewards(), [oracle.utilities[p][t, mask]/oracle.utility_scale
                                                            for p, t in enumerate(actual)], atol=1e-12)
    # Set exactly one required bit on a linear goal: fractional rewards must survive.
    state.commitments[:] = 0
    goal = next(g for g in spec.goals if not g.binary)
    action = goal.required_actions[0]
    state.commitments[action.player_id, action.action_id] = 1
    assert state.goal_satisfaction()[goal.goal_id] == 1 / len(goal.required_actions)
    observation = build_player_observation(state, 0)
    facts = observation.to_agent_dict()
    assert facts['goals'][f'G{goal.goal_id}']['type'] == 'LINEAR'
    assert facts['current_state_facts']['your_utility_if_terminal'] == pytest.approx(state.reward(0))
    oracle.clear_caches()


def test_structure_grouping_ignores_all_relabelings_and_goal_types():
    spec = generate_game(3, GeneratorConfig(n_players=5, actions_per_player=3, n_goals=12))
    players, actions = [4, 2, 0, 3, 1], [2, 0, 1]
    goals = tuple(Goal(i, tuple(ActionRef(players[a.player_id], actions[a.action_id]) for a in g.required_actions), False)
                  for i, g in enumerate(reversed(spec.goals)))
    renamed = replace(spec, goals=goals)
    assert structure_fingerprint(spec) == structure_fingerprint(renamed)


def test_plan_counts_roles_and_ood_isolation():
    plan = plan_sources()
    assert len(plan) == 220
    assert len({p['seed'] for p in plan}) == 220
    for split in ('train', 'validation', 'test'):
        assert {p['config']['n_players'] for p in plan if p['split'] == split} == {3, 4}
    assert {p['config']['n_players'] for p in plan if p['split'] == 'ood_test'} == {5}
    for n in (3, 4):
        assert {p['learner'] for p in plan if p['split']=='train' and p['config']['n_players']==n} == set(range(n))
    assert {p['config']['linear_goal_fraction'] for p in plan if p['split']=='train'} == {0, .5, 1}


@pytest.mark.parametrize('players,fraction', [(3, 0), (4, .5), (5, 1)])
def test_independent_public_replay_and_whole_pairs(players, fraction):
    config = GeneratorConfig(n_players=players, actions_per_player=2, n_goals=6, n_rounds=1,
                             linear_goal_fraction=fraction)
    budget = Budget(simulations=32)
    game, raw, _, pairs = audit_game(76200+players, 'test', budget, backgrounds=3, config=config,
                                    learner_id=players-1, explicit_world_limit=0,
                                    topology_fn=structure_fingerprint)
    assert not game['stats']['explicit_joint_support_verified']
    assert game['stats']['initial_hidden_worlds'] == 27**(players-1)
    selected, selected_pairs = select_pairs(raw, pairs, 16)
    assert len(selected) <= 16
    ids = {r['id'] for r in selected}
    assert all(p['before'] in ids and p['after'] in ids for p in selected_pairs)
    # Every selected non-initial question belongs to a retained complete pair.
    endpoints = {p[k] for p in selected_pairs for k in ('before', 'after')}
    assert all(not r['input']['history'] or r['id'] in endpoints for r in selected)
    assert replay_public(selected, budget)['verified_questions'] == len(selected)
    mutated = deepcopy(selected)
    for r in mutated:
        r['certificate'] = {'made_up_private_row': [1]*6}
    assert replay_public(mutated, budget)['stored_certificates_used'] is False
    mutated[0]['answer'] = {'possible_preferences': []}
    with pytest.raises(ValueError, match='Gold'):
        replay_public(mutated, budget)
    sample = chat(selected[0])
    assert 'LINEAR' in sample['messages'][0]['content']
    assert 'Return only one SUBMIT_JUDGMENT' in sample['messages'][0]['content']
    assert 'certificate' not in sample['messages'][1]['content']
    assert not sample['messages'][-1]['content']


def test_goal_validation_and_binary_generator_preservation():
    with pytest.raises(ValueError):
        Goal(0, (ActionRef(0, 0), ActionRef(1, 0)), binary='false')
    binary = generate_game(7, GeneratorConfig())
    linear = generate_game(7, GeneratorConfig(linear_goal_fraction=1))
    assert [g.required_actions for g in binary.goals] == [g.required_actions for g in linear.goals]
    assert binary.round_robin == linear.round_robin
    np.testing.assert_array_equal(binary.private_preferences, linear.private_preferences)


def test_corpus_resumes_completed_sources_after_export_interruption(tmp_path, monkeypatch):
    import json
    import benac_p.b_corpus as corpus
    tokenizer = tmp_path/'tokenizer'
    tokenizer.mkdir()
    for name in ('tokenizer.json', 'tokenizer_config.json'):
        (tokenizer/name).write_text('{}')
    root = tmp_path/'corpus'
    args = ['--output-dir', str(root), '--tokenizer-dir', str(tokenizer), '--train-games', '1',
            '--validation-games', '1', '--test-games', '1', '--ood-games', '1',
            '--simulations', '8', '--backgrounds', '3', '--samples-per-game', '8']
    export = corpus.export_dataset
    def interrupted(*args):
        raise RuntimeError('simulated export interruption')
    monkeypatch.setattr(corpus, 'export_dataset', interrupted)
    with pytest.raises(RuntimeError, match='simulated'):
        corpus.main(args)
    assert len(list((root/'sources').glob('*/complete.json'))) == 4
    assert not (root/'READY.json').exists()
    monkeypatch.setattr(corpus, 'export_dataset', export)
    monkeypatch.setattr(corpus, 'token_audit', lambda samples, directory: dict(records=[
        dict(id=s['id'], total_tokens=100, prompt_tokens=90) for s in samples]))
    def no_regeneration(*args, **kwargs):
        raise AssertionError('Completed source should not be generated again')
    monkeypatch.setattr(corpus, 'audit_game', no_regeneration)
    # Exact old serial scheduler can resume, including with a new worker count.
    manifest = json.loads((root/'manifest.json').read_text())
    manifest['source_sha256']['b_corpus.py'] = corpus.SERIAL_SCHEDULER_SHA256
    (root/'manifest.json').write_text(json.dumps(manifest))
    corpus.main(args + ['--resume', '--workers', '2'])
    summary = json.loads((root/'summary.json').read_text())
    assert summary['complete'] and (root/'READY.json').is_file()
    for split in corpus.SPLITS:
        rows = [json.loads(x) for x in (root/f'{split}.jsonl').read_text().splitlines()]
        pairs = [json.loads(x) for x in (root/f'{split}_pairs.jsonl').read_text().splitlines()]
        ids = {r['id'] for r in rows}
        assert all(p['before'] in ids and p['after'] in ids for p in pairs)
    with pytest.raises(SystemExit):
        corpus.main(args + ['--resume'])
    from benac_p.b_corpus_snapshot import snapshot
    frozen = tmp_path/'frozen'
    # OOD need not be completed for the training snapshot.
    (root/'sources'/'source-0003'/'complete.json').unlink()
    result = snapshot(root, frozen)
    assert result['full_corpus_complete'] is False
    assert set(result['splits']) == {'train', 'validation', 'test'}
    assert (frozen/'READY.json').exists()
    assert not (frozen/'ood_test.jsonl').exists()
    assert (frozen/'train.jsonl').read_bytes() == (root/'train.jsonl').read_bytes()
    with pytest.raises(ValueError, match='fresh'):
        snapshot(root, frozen)
    (root/'sources'/'source-0000'/'complete.json').unlink()
    with pytest.raises(ValueError, match='unfinished'):
        snapshot(root, tmp_path/'unfinished')


def test_parallel_resume_does_not_relax_oracle_or_config_checks():
    from copy import deepcopy
    from benac_p.b_corpus import resume_matches, SERIAL_SCHEDULER_SHA256
    current = dict(source_sha256={'b_corpus.py': 'new', 'mcts_oracle.py': 'oracle'},
                   configuration={'simulations': 1024})
    previous = deepcopy(current)
    previous['source_sha256']['b_corpus.py'] = SERIAL_SCHEDULER_SHA256
    assert resume_matches(previous, current)
    previous['source_sha256']['mcts_oracle.py'] = 'different'
    assert not resume_matches(previous, current)
    previous = deepcopy(current)
    previous['configuration']['simulations'] = 8
    assert not resume_matches(previous, current)


def test_reference_solver_does_not_truncate_linear_terminal_rewards():
    from benac_p.solver import PerfectInfoSolver
    spec = GameSpec(n_players=2, n_actions_per_player=(1, 1),
                    goals=(Goal(0, (ActionRef(0, 0), ActionRef(1, 0)), False),),
                    private_preferences=np.asarray([[1], [-1]]), round_robin=(0,), max_changes=1, seed=0)
    state = GameState(spec)
    state.commitments[0, 0] = 1
    state.turn_index = 1
    assert PerfectInfoSolver(spec).solve(state).values == (.5, -.5)
