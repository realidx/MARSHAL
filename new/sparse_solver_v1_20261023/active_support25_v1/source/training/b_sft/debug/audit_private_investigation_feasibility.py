"""Restricted information-use audit, NOT a private-information game solver.

The final-proposal fixture has an informed responder (the queried player).
The only uninformed third player has identical response policies in both
worlds. Thus its full-information branches can be coupled without leakage.
This proves a value for using a private result at a fixed decision, not the
net value of spending an earlier turn to acquire that result.
"""
import argparse
import json
from fractions import Fraction
from pathlib import Path

import numpy as np

from training.b_sft.social_bp_curriculum import result_use_fixture
from training.b_sft.social_terminal_teacher import TerminalEpisode
from training.b_sft.debug.audit_social_design_iteration import independent_values
from training.b_sft.social_b_oracle import canonical


def audit():
    episodes = []
    rows = []
    for value in ('want', 'avoid'):
        raw, prefix = result_use_fixture(value)
        episode = TerminalEpisode(raw, prefix)
        native = independent_values(episode.tree)
        choices = episode.choices(raw['own_preferences'])
        episodes.append(episode)
        rows.append(dict(value=value, native=native, actions=choices['actions'],
                         values=choices['values']))
    left, right = episodes
    assert rows[0]['actions'] == rows[1]['actions']
    assert left.tree.entries[0].node.state.snapshot_commitments() == right.tree.entries[0].node.state.snapshot_commitments()
    assert len(left.tree.entries) == len(right.tree.entries)
    third_player_checks = 0
    for i, (a, b) in enumerate(zip(left.tree.entries, right.tree.entries)):
        assert a.actor == b.actor
        if a.actor == 2:
            assert [x.to_dict() for x in a.actions] == [x.to_dict() for x in b.actions]
            np.testing.assert_array_equal(left.tree.policy[i], right.tree.policy[i])
            # Player 2 only responds; it gets no new proposal after this point.
            assert all('response' in x.to_dict() for x in a.actions)
            third_player_checks += 1
    assert third_player_checks
    payoff = [[Fraction(str(v[0])) for v in r['values']] for r in rows]
    blind = max((a+b)/2 for a, b in zip(*payoff))
    informed = sum(max(row) for row in payoff)/2
    assert (blind, informed) == (Fraction(1), Fraction(3, 2))

    # Independent last-turn cost check: replace the earlier imposed query with
    # PASS, so the quota remains available and the same physical state is reached.
    raw, prefix = result_use_fixture('want')
    prefix[3] = dict(action='PASS')
    deadline = TerminalEpisode(raw, prefix)
    independent_values(deadline.tree)
    choices = deadline.choices(raw['own_preferences'])
    query_values = [v[0] for a, v in zip(choices['actions'], choices['values'])
                    if a.get('action') == 'INVESTIGATE']
    assert query_values and all(v == 0 for v in query_values)
    ordinary = max(v[0] for a, v in zip(choices['actions'], choices['values'])
                   if a.get('action') != 'INVESTIGATE')
    assert ordinary == 1
    return dict(
        version='private-investigate-feasibility-v1', actual_LM=False,
        private_solver_implemented=False, training_ready=False,
        proposed_quota='one investigation per player per game',
        visibility='proposed: action and target public, answer to investigator only',
        prior='two teaching types with equal support',
        final_action_values=[dict(action=a, want=str(payoff[0][i]), avoid=str(payoff[1][i]))
                             for i, a in enumerate(rows[0]['actions'])],
        private_result_use=dict(best_without_result=str(blind),
            best_conditioned_on_result=str(informed), gain=str(informed-blind),
            uninformed_third_player_policy_checks=third_player_checks,
            scope='Same final decision and physical state; acquisition cost excluded. '
                  'Setup is imposed, not voluntary behavioral evidence. The queried '
                  'responder knows its own type; the third player uses the same policy '
                  'across both hidden results. No public result is needed for these values.'),
        deadline=dict(query_value=0, best_ordinary_value=ordinary,
            scope='Query consumes the last proposal; no player can act on its answer. '
                  'Result visibility and other players remaining quotas cannot change this.'),
        open_requirements=[
            'Net positive acquisition value against every legal offer/pass continuation',
            'Full normal rotation with each player retaining its own query quota',
            'Information sets coupled across unobserved result branches',
            'Delay/target-choice contrasts and fresh policy verification'],
    )


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    result = audit()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=False)
    (out/'audit.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))
