"""Isolated next-own-decision evaluator; never changes production defaults."""
import hashlib
import json

from training.strategic_slices.bounded import BoundedPrivateWindow

VERSION = 'next-own-proposal-commitment-window-v1'


def decision_horizon(rules, root):
    """Finish the next focal proposal and its response, or native game end.

    In a cyclic proposal schedule, a proposal entrance includes n+1 proposal
    opportunities. A response entrance includes its pending response and ends
    after the responder's next proposal, without an additional RR minimum.
    Every action branch shares the endpoint chosen from the entrance alone.
    """
    if root.state.is_terminal:
        raise ValueError('A terminal state has no decision window')
    schedule = rules.spec.round_robin
    turn = root.state.turn_index
    focal = rules.actor(root)
    next_own = next((j for j in range(turn + 1, len(schedule))
                     if schedule[j] == focal), None)
    cutoff = len(schedule) if next_own is None else next_own + 1
    return dict(horizon_mode=VERSION, lookahead_rr=1,
                proposal_turns=cutoff-turn, root_turn_index=turn,
                root_actor=focal, root_phase=('response' if root.pending else 'proposal'),
                base_cutoff=min(turn+rules.spec.n_players, len(schedule)),
                cutoff=cutoff, next_own_proposal_index=next_own,
                next_own_proposal_included=next_own is not None,
                actual_proposal_turns=cutoff-turn,
                terminal_truncated_horizon=next_own is None)


class DecisionWindow(BoundedPrivateWindow):
    """Reuse native transitions, information sets, search and full local audit.

    The base constructor invokes _grow once for the entrance before any child
    exists. Set the isolated endpoint there, before recursive expansion starts.
    No existing module, global function or frozen source file is patched.
    """
    def __init__(self, rules, root, worlds, **options):
        if 'lookahead_rr' in options or 'horizon_mode' in options:
            raise ValueError('This research version has one fixed horizon contract')
        super().__init__(rules, root, worlds, lookahead_rr=1, **options)

    def _grow(self, node):
        if not self.entries:
            self.horizon = decision_horizon(self.rules, node)
            for key, value in self.horizon.items():
                setattr(self, key, value)
        return super()._grow(node)

    def reference_identity(self):
        old_hash, checks = super().reference_identity()
        identity = json.dumps(dict(research_version=VERSION, base_identity=old_hash),
                              sort_keys=True).encode()
        return hashlib.sha256(identity).hexdigest(), checks

    def _solve_and_certify(self):
        super()._solve_and_certify()
        self.certificate.update(research_version=VERSION,
            original_terminal_optimality_claim=False,
            scope='Certified only for the entrance-anchored next-own-proposal '
                  'window with current commitment utility at its common boundary; '
                  'not a rolling-horizon or original full-game equilibrium claim.')
        return self
