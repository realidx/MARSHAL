"""Finite-horizon best response to known stochastic partners, given a belief.

Ego choices maximize terminal own utility. Partner actions are chance nodes
whose predictive probabilities and posterior updates use the supplied joint
belief. There is no access to true partner preferences or prior reconstruction.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import math
from typing import Mapping

import numpy as np

from benac_p.belief import BeliefState, condition_belief
from benac_p.controlled import SoftProgressPolicy
from benac_p.observations import PlayerObservation, build_player_observation
from benac_p.schema import (
    GameSpec, MenuOffer, Offer, response_actions, OfferProposal, PassProposal, ResponseAction, PREFERENCE_TO_VALUE,
)
from benac_p.state import GameState

Action = PassProposal | OfferProposal | ResponseAction


class BayesPlannerLimitError(RuntimeError):
    """Full terminal search exceeded an explicit diagnostic budget."""


@dataclass(frozen=True)
class ActionValue:
    action: Action
    value: float

    def to_dict(self):
        return {"action": self.action.to_dict(), "value": self.value}


@dataclass(frozen=True)
class BayesPlannerResult:
    value: float
    action: Action | None
    optimal_actions: tuple[Action, ...]
    action_values: tuple[ActionValue, ...]
    nodes_expanded: int
    kernel_nodes: int
    remaining_turns: int
    support_size: int

    def regret(self, action: Action) -> float:
        for candidate in self.action_values:
            if candidate.action == action or (
                isinstance(candidate.action, OfferProposal) and isinstance(action, OfferProposal)
                and isinstance(candidate.action.offer, MenuOffer) and isinstance(action.offer, MenuOffer)
                and frozenset(candidate.action.offer.offers) == frozenset(action.offer.offers)
            ):
                return max(0.0, self.value - candidate.value)
        raise ValueError("Regret requires a legal ego action at the evaluated decision.")

    def to_dict(self):
        return {
            "value": self.value, "action": None if self.action is None else self.action.to_dict(),
            "optimal_actions": [a.to_dict() for a in self.optimal_actions],
            "action_values": [v.to_dict() for v in self.action_values],
            "nodes_expanded": self.nodes_expanded, "kernel_nodes": self.kernel_nodes,
            "remaining_turns": self.remaining_turns, "support_size": self.support_size,
        }


class BayesPlanner:
    """Bounded exact search, not a truncated-horizon approximation.

    solve() can value any public phase; action values are returned only at an
    ego decision. act() requires an ego decision. A pending partner proposal
    is assumed already incorporated in the supplied belief, and is not updated
    again. Different calls always start fresh caches. Only Markov
    SoftProgressPolicy kernels are supported; hence raw history is not needed.
    """

    VERSION = "bayes-expectimax-v1"

    def __init__(
        self, *, partner_policies: Mapping[int, SoftProgressPolicy] | None = None,
        max_remaining_turns: int = 4, max_nodes: int = 50_000,
        max_hypotheses: int = 4096, tie_tolerance: float = 1e-10,
    ):
        for name, value in (("max_remaining_turns", max_remaining_turns),
                            ("max_nodes", max_nodes), ("max_hypotheses", max_hypotheses)):
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"{name} must be a positive integer.")
        if not math.isfinite(tie_tolerance) or tie_tolerance < 0:
            raise ValueError("tie_tolerance must be finite and nonnegative.")
        self.max_remaining_turns = max_remaining_turns
        self.max_nodes = max_nodes
        self.max_hypotheses = max_hypotheses
        self.tie_tolerance = tie_tolerance
        self._policies = None if partner_policies is None else {}
        for player, policy in (partner_policies or {}).items():
            if type(policy) is not SoftProgressPolicy:
                raise TypeError("BayesPlanner v1 supports SoftProgressPolicy kernels only.")
            self._policies[player] = SoftProgressPolicy(
                seed=0, temperature=policy.temperature, progress_weight=policy.progress_weight,
                uniform_mix=policy.uniform_mix,
            )

    def specification(self):
        return {
            "version": self.VERSION, "max_remaining_turns": self.max_remaining_turns,
            "max_nodes": self.max_nodes, "max_hypotheses": self.max_hypotheses,
            "tie_tolerance": self.tie_tolerance,
            "tie_rule": "first within tolerance: PASS/REJECT before offers/ACCEPT",
            "objective": "own terminal ALL_OF utility; full remaining schedule; no discount",
            "future_beliefs": "Bayesian updates after non-ego actions only",
            "partner_policies": (
                {str(i): p.specification() for i, p in self._policies.items()}
                if self._policies is not None else {"all_partners": SoftProgressPolicy().specification()}
            ),
        }

    def solve(self, observation: PlayerObservation, belief: BeliefState) -> BayesPlannerResult:
        problem = _Search(self, observation, belief)
        value, action_values = problem.evaluate(problem.root, belief, observation.pending_offer)
        optimal = tuple(v.action for v in action_values if value - v.value <= self.tie_tolerance)
        return BayesPlannerResult(
            value, optimal[0] if optimal else None, optimal, action_values,
            problem.nodes, len(problem.kernel_cache),
            len(observation.round_robin) - observation.turn_index, len(belief.hypotheses),
        )

    def act(self, observation: PlayerObservation, belief: BeliefState) -> Action:
        is_ego_decision = (
            observation.pending_offer.partner_id == observation.player_id
            if observation.pending_offer is not None else observation.is_proposer
        )
        if not is_ego_decision:
            raise ValueError("act() requires an ego proposal or response decision.")
        result = self.solve(observation, belief)
        if result.action is None:
            raise ValueError("There is no ego action at this state.")
        return result.action


class _Search:
    def __init__(self, planner: BayesPlanner, obs: PlayerObservation, belief: BeliefState):
        self.planner = planner
        self.ego_id = obs.player_id
        if not 0 <= self.ego_id < obs.n_players or obs.own_preferences is None:
            raise ValueError("Planner requires ego identity and own preferences.")
        if len(obs.own_preferences) != len(obs.goals):
            raise ValueError("Own preferences must align with goals.")
        if not 0 <= obs.turn_index <= len(obs.round_robin):
            raise ValueError("turn_index is outside the schedule.")
        remaining = len(obs.round_robin) - obs.turn_index
        if remaining > planner.max_remaining_turns or len(belief.hypotheses) > planner.max_hypotheses:
            raise BayesPlannerLimitError(
                f"Exact search requested {remaining} remaining turns and {len(belief.hypotheses)} "
                "hypotheses, exceeding configured budget. No truncated value was returned."
            )
        partners = set(range(obs.n_players)) - {self.ego_id}
        if set(belief.partner_ids) != partners or len(belief.hypotheses[0][0]) != len(obs.goals):
            raise ValueError("Belief must cover exactly the other players and all goals.")
        self.policies = planner._policies if planner._policies is not None else {
            i: SoftProgressPolicy(seed=0) for i in partners
        }
        if set(self.policies) != partners:
            raise ValueError("Specify exactly one kernel per non-ego partner.")
        self.own_values = tuple(PREFERENCE_TO_VALUE[v] for v in obs.own_preferences)
        # No true private matrix, original seed, metadata or transcript enters search.
        self.root = GameState(GameSpec(
            n_players=obs.n_players, n_actions_per_player=obs.n_actions_per_player,
            goals=obs.goals, private_preferences=np.zeros((obs.n_players, len(obs.goals)), dtype=np.int8),
            round_robin=obs.round_robin, max_changes=obs.max_changes, seed=0,
            forbidden_actions=obs.forbidden_actions, menu_enabled=obs.menu_enabled,
        ))
        if len(obs.commitments) != obs.n_players:
            raise ValueError("Commitments must contain every player.")
        for player, row in enumerate(obs.commitments):
            if len(row) != obs.n_actions_per_player[player] or any(v not in (0, 1) for v in row):
                raise ValueError("Invalid commitment row.")
            if obs.forbidden_actions is not None and any(
                v and obs.forbidden_actions[player][a] for a, v in enumerate(row)
            ):
                raise ValueError("State includes a forbidden commitment.")
            self.root.commitments[player, :len(row)] = row
        self.root.turn_index = obs.turn_index
        if self.root.current_proposer() != obs.current_proposer:
            raise ValueError("Current proposer disagrees with schedule.")
        if obs.pending_offer is not None:
            if obs.pending_proposer_id not in (None, obs.current_proposer):
                raise ValueError("Pending proposer disagrees with schedule.")
            self.root.validate_offer(obs.pending_offer)
        self.cache = {}
        self.kernel_cache = {}
        self.nodes = 0
        self.rows = {}
        self.row_indices = {}
        for column, player in enumerate(belief.partner_ids):
            rows = tuple(dict.fromkeys(h[column] for h in belief.hypotheses))
            indices = {row: i for i, row in enumerate(rows)}
            self.rows[player] = rows
            self.row_indices[player] = np.array([indices[h[column]] for h in belief.hypotheses])

    @staticmethod
    def state_key(state, pending):
        return state.turn_index, state.snapshot_commitments(), pending

    def kernel(self, state, pending, actor):
        key = self.state_key(state, pending)
        if key not in self.kernel_cache:
            obs = build_player_observation(
                state, actor, mode="public", pending_offer=pending,
                pending_proposer_id=state.current_proposer() if pending is not None else None,
            )
            distributions = []
            for row in self.rows[actor]:
                candidate = replace(obs, own_preferences=row)
                policy = self.policies[actor]
                distribution = (
                    policy.proposal_distribution(candidate) if pending is None
                    else policy.response_distribution(candidate, pending)
                )
                distributions.append(distribution)
            actions = tuple(a for a, _ in distributions[0])
            probabilities = np.array([[p for _, p in d] for d in distributions])
            self.kernel_cache[key] = actions, probabilities[self.row_indices[actor]]
        return self.kernel_cache[key]

    def successor_value(self, state, belief, pending, action):
        if isinstance(action, OfferProposal):
            return self.evaluate(state, belief, action.offer)[0]
        child = state.clone()
        if isinstance(action, PassProposal):
            child.apply_pass()
        else:
            child.resolve_offer(pending, action)
        return self.evaluate(child, belief, None)[0]

    def evaluate(self, state, belief, pending):
        key = (*self.state_key(state, pending), belief.log_probabilities)
        if key in self.cache:
            return self.cache[key]
        if self.nodes >= self.planner.max_nodes:
            raise BayesPlannerLimitError(
                f"Exact search exceeded max_nodes={self.planner.max_nodes}. No partial value was returned."
            )
        self.nodes += 1
        if state.is_terminal:
            result = (float(np.dot(self.own_values, state.goal_satisfaction())), ())
        else:
            actor = state.current_proposer() if pending is None else pending.partner_id
            if actor == self.ego_id:
                actions = state.legal_proposals() if pending is None else response_actions(pending)
                values = tuple(ActionValue(a, self.successor_value(state, belief, pending, a)) for a in actions)
                result = (max(v.value for v in values), values)
            else:
                actions, likelihoods = self.kernel(state, pending, actor)
                branches = []
                for index, action in enumerate(actions):
                    posterior, log_probability = condition_belief(belief, likelihoods[:, index])
                    value = self.successor_value(state, posterior, pending, action)
                    branches.append(math.exp(log_probability) * value)
                result = (math.fsum(branches), ())
        self.cache[key] = result
        return result
