"""Checks for dataset correctness, rather than learner performance."""
import json

from benac_p.sft_data_audit import Audit, OPTIONS, decode_action, export, summarize


def test_exact_examples_replay_and_preserve_all_optimal_actions(tmp_path):
    audit = Audit(50001)
    game = audit.run()
    assert all(t['completed'] for t in game['trajectories'])
    assert not game['failures']
    assert game['independent_search_checked']
    cases = {c['id']: c for c in game['cases']}
    for c in cases.values():
        node = audit.search.replay([decode_action(a) for a in c['history']])
        assert audit.support(node) == c['support']
        if c['planning_status'] != 'exact':
            continue
        q = dict(audit.search.q_values(node))
        best = max(q.values())
        expected = [i for i, a in enumerate(c['actions']) if best-q[decode_action(a)] < 1e-9]
        assert expected == c['optimal_indices']
        assert c['demonstration_index'] in expected
        assert c['selected_action_branch_accounting_verified']
    for intervention in game['interventions']:
        assert abs(sum(b['weight'] for b in intervention['branches']) - 1) < 1e-9
    for s in game['samples']:
        if s['kind'] == 'semantic_belief':
            assert s['tools'][0]['function']['parameters']['properties']['possible_preferences']['items']['enum'] == OPTIONS
            if not s['input']['history']:
                assert s['answer']['possible_preferences'] == s['input']['initially_possible_preferences']
        else:
            c = cases[s['case_id']]
            assert s['answer']['action_index'] in c['optimal_indices']
    export(tmp_path, [game], dict(seed=50001, games=1))
    rows = [json.loads(line) for line in (tmp_path/'examples.jsonl').read_text().splitlines()]
    for row in rows:
        assert row['split'] == 'development_audit_only'
        payload = json.loads(row['messages'][1]['content'])
        assert set(payload).isdisjoint({'seed', 'source_game', 'condition', 'q', 'answer', 'worlds'})
        assert set(payload['game']).isdisjoint({'seed', 'private_preferences', 'metadata'})
        assert len(row['messages'][2]['tool_calls']) == 1


def test_seed_reproducibility_excludes_wall_clock():
    def without_times(value):
        if isinstance(value, dict):
            return {k: without_times(v) for k, v in value.items() if not k.endswith('_seconds')}
        if isinstance(value, list):
            return [without_times(v) for v in value]
        return value
    assert without_times(Audit(50000).run()) == without_times(Audit(50000).run())


def test_budget_failure_never_becomes_approximate_planning_label():
    game = Audit(50001, max_nodes=1).run()
    assert game['failures']
    cases = {c['id']: c for c in game['cases']}
    for s in game['samples']:
        if s['kind'] == 'planning':
            assert cases[s['case_id']]['planning_status'] == 'exact'
    assert summarize([game])['source_games'] == 1


def test_actual_world_draw_is_from_declared_catalogue_and_not_source_row():
    game = Audit(50000).run()
    # This seed's independent world draws differ from the generator's private row.
    realized = [t['realized_world'][game['target']][game['goal']] for t in game['trajectories']]
    original = game['source_spec']['private_preferences'][game['target']][game['goal']]
    assert any(v != original for v in realized)
    for t in game['trajectories']:
        for p, row in enumerate(t['realized_world']):
            assert row in game['type_catalogues'][str(p)]
