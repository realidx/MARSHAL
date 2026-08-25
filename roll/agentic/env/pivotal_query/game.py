"""Pure Python partner-aware Pivotal Query state machine."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from .oracle import ExactQueryOracle
from .types import PivotalQueryInstance


class PivotalQueryGame:
    def __init__(self, instance: PivotalQueryInstance, max_queries: int = 3):
        self.instance = instance
        self.max_queries = max_queries
        self.oracle = ExactQueryOracle(instance)
        self.known = instance.known_dict()
        self.attempted_queries: List[Tuple[str, str]] = []
        self.records: List[Dict[str, Any]] = []
        self.done = False
        self.total_reward = 0.0
        self.final_option = None
        self.initial_decision = self.oracle.solve(
            self.known,
            available_queries=self.instance.all_queries(),
            queries_left=self.max_queries,
        )

    def available_queries(self):
        attempted = set(self.attempted_queries)
        return tuple(
            query for query in self.instance.all_queries() if query not in attempted and query[1] not in self.known
        )

    def legal_actions(self):
        if self.done:
            return ()
        asks = ()
        if len(self.attempted_queries) < self.max_queries:
            asks = tuple(f"ASK {partner} {fact}" for partner, fact in self.available_queries())
        acts = tuple(f"ACT {option}" for option in self.instance.option_names)
        return asks + acts

    def step(self, action: str):
        if self.done:
            raise RuntimeError("cannot act in a finished Pivotal Query game")
        if action not in self.legal_actions():
            raise ValueError(f"illegal Pivotal Query action {action!r}")

        decision = self.oracle.solve(
            self.known,
            available_queries=self.available_queries(),
            queries_left=self.max_queries - len(self.attempted_queries),
        )
        action_value = decision.action_value(action)
        is_ask = action.startswith("ASK ")
        query_values = dict(decision.query_values)
        best_query_value = decision.best_query_value

        partner = None
        fact = None
        source_capable = False
        fact_relevant = False
        if is_ask:
            _, partner, fact = action.split()
            source_capable = self.instance.partner_knows(partner, fact)
            fact_relevant = fact == self.instance.pivotal_fact

        record = {
            "action": action,
            "action_is_ask": float(is_ask),
            "oracle_should_ask": float(decision.should_ask),
            "oracle_value": decision.value,
            "oracle_best_act_value": decision.best_act_value,
            "oracle_best_query_value": best_query_value,
            "chosen_action_value": action_value,
            "decision_regret": max(0.0, decision.value - action_value),
            "optimal_action": float(action in decision.optimal_actions),
            "query_regret": (
                max(0.0, best_query_value - query_values[action]) if is_ask and best_query_value is not None else None
            ),
            "post_sufficiency_excess_ask": float(is_ask and not decision.should_ask),
            "query_fact_relevant": float(fact_relevant),
            "query_source_capable": float(source_capable),
            "query_route_optimal": float(is_ask and action in decision.optimal_actions),
            "unproductive_query": float(is_ask and not source_capable),
        }
        self.records.append(record)

        if is_ask:
            assert partner is not None and fact is not None
            self.attempted_queries.append((partner, fact))
            reward = -self.instance.query_cost(partner, fact)
            if source_capable:
                answer = self.instance.actual_value(fact)
                self.known[fact] = answer
                observation = f"{partner} answers: {fact} = {answer}."
            else:
                observation = f"{partner} answers: I do not know {fact}."
        else:
            option = action.removeprefix("ACT ")
            self.final_option = option
            reward = self.instance.actual_payoff(option)
            self.done = True
            observation = f"Final choice: {option}. Realized payoff: {reward:g}."
        self.total_reward += reward

        info = dict(record)
        info.update(
            {
                "condition": self.instance.condition,
                "family_id": self.instance.family_id,
                "pivotal_fact": self.instance.pivotal_fact,
                "num_asks": float(len(self.attempted_queries)),
                "step_reward": reward,
                "game_transition": 1.0,
            }
        )
        if self.done:
            info.update(self.terminal_metrics())
        return observation, reward, self.done, info

    def terminal_metrics(self):
        first = self.records[0]
        first_ask = bool(first["action_is_ask"])
        initially_should_ask = self.initial_decision.should_ask
        first_targeted = first["action"] in self.initial_decision.optimal_actions if first_ask else False
        return {
            "success": True,
            "total_return": self.total_reward,
            "initial_should_ask": float(initially_should_ask),
            "first_action_ask": float(first_ask),
            "necessary_ask_hit": float(initially_should_ask and first_ask),
            "unnecessary_ask": float((not initially_should_ask) and first_ask),
            "first_query_targeted": float(first_targeted),
            "first_query_fact_relevant": first["query_fact_relevant"],
            "first_query_source_capable": first["query_source_capable"],
            "first_query_route_optimal": first["query_route_optimal"],
            "first_decision_optimal": first["optimal_action"],
            "total_query_regret": sum(record["query_regret"] or 0.0 for record in self.records),
            "post_sufficiency_excess_communication": sum(
                record["post_sufficiency_excess_ask"] for record in self.records
            ),
            "unproductive_queries": sum(record["unproductive_query"] for record in self.records),
            "num_asks": float(len(self.attempted_queries)),
        }
