"""Strict one-ASK Hidden Choice state machine and failure taxonomy."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .oracle import OneShotVOIOracle
from .types import HiddenChoiceInstance


class HiddenChoiceGame:
    def __init__(self, instance: HiddenChoiceInstance, full_information: bool = False):
        self.instance = instance
        self.oracle = OneShotVOIOracle(instance)
        self.full_information = bool(full_information)
        self.known: Dict[str, str] = (
            dict(zip(instance.fact_names, instance.actual_values))
            if self.full_information
            else {}
        )
        self.query_used = False
        self.records: List[Dict[str, Any]] = []
        self.done = False
        self.total_reward = 0.0
        self.final_option: Optional[str] = None
        self.communication_decision = self.oracle.solve()
        self.initial_decision = self.oracle.solve(
            self.known, allow_questions=not self.full_information
        )

    def legal_actions(self):
        if self.done:
            return ()
        legal = {f"ACT {option}" for option in self.instance.option_names}
        if not self.full_information and not self.query_used:
            legal.update(f"ASK {question}" for question, _ in self.instance.questions)
        return tuple(action for action in self.instance.action_order if action in legal)

    def step(self, action: str):
        if self.done:
            raise RuntimeError("cannot act in a finished Hidden Choice game")
        if action not in self.legal_actions():
            raise ValueError(f"illegal Hidden Choice action {action!r}")

        decision = self.oracle.solve(
            self.known,
            allow_questions=not self.full_information and not self.query_used,
        )
        is_ask = action.startswith("ASK ")
        query_correct = bool(is_ask and action in decision.best_questions)
        record = {
            "action": action,
            "action_is_ask": float(is_ask),
            "oracle_should_ask": float(decision.should_ask),
            "oracle_value_act": decision.value_act,
            "oracle_value": decision.value,
            "chosen_action_value": decision.action_value(action),
            "decision_regret": max(0.0, decision.value - decision.action_value(action)),
            "optimal_action": float(action in decision.optimal_actions),
            "query_correct": float(query_correct),
        }
        self.records.append(record)

        if is_ask:
            question = action.removeprefix("ASK ")
            fact = self.instance.question_fact(question)
            answer = self.instance.actual_value(fact)
            self.known[fact] = answer
            self.query_used = True
            reward = -self.instance.communication_cost
            observation = f"Partner answers: {question} reveals {fact} = {answer}."
        else:
            option = action.removeprefix("ACT ")
            self.final_option = option
            reward = self.instance.actual_utility(option)
            self.done = True
            observation = f"Final choice: {option}. Realized utility: {reward:g}."
        self.total_reward += reward

        info = dict(record)
        info.update(
            {
                "condition": self.instance.condition,
                "family_id": self.instance.family_id,
                "full_information": float(self.full_information),
                "step_reward": reward,
                "num_asks": float(self.query_used),
                "game_transition": 1.0,
            }
        )
        if self.done:
            info.update(self.terminal_metrics())
        return observation, reward, self.done, info

    def terminal_metrics(self, stopping_failure: bool = False):
        if not self.records:
            raise RuntimeError("terminal metrics require at least one decision")
        first = self.records[0]
        first_ask = bool(first["action_is_ask"])
        should_ask = self.communication_decision.should_ask
        first_optimal = bool(first["optimal_action"])
        final_record = next(
            (record for record in reversed(self.records) if not record["action_is_ask"]),
            None,
        )
        final_correct = bool(final_record and final_record["optimal_action"])
        correct_query = bool(first_ask and first["query_correct"])
        if self.full_information:
            benchmark_success = bool(not first_ask and first_optimal)
        else:
            benchmark_success = (
                (not should_ask and not first_ask and first_optimal)
                or (should_ask and correct_query and final_correct and not stopping_failure)
            )
        max_voi = max(
            (value for _, value in self.communication_decision.gross_voi),
            default=0.0,
        )
        return {
            "success": True,
            "benchmark_success": float(benchmark_success),
            "total_return": self.total_reward,
            "initial_should_ask": float(should_ask),
            "full_information": float(self.full_information),
            "max_gross_voi": max_voi,
            "communication_cost": self.instance.communication_cost,
            "oracle_margin": max_voi - self.instance.communication_cost,
            "first_action_ask": float(first_ask),
            "first_decision_optimal": float(first_optimal),
            "ask_act_correct": float(first_optimal),
            "correct_abstention": float(
                not self.full_information and not should_ask and not first_ask and first_optimal
            ),
            "over_querying": float(not self.full_information and not should_ask and first_ask),
            "decision_error": float(
                not self.full_information and not should_ask and not first_ask and not first_optimal
            ),
            "under_querying": float(not self.full_information and should_ask and not first_ask),
            "query_selection_failure": float(
                not self.full_information and should_ask and first_ask and not correct_query
            ),
            "query_selection_correct": float(
                not self.full_information and should_ask and first_ask and correct_query
            ),
            "information_use_failure": float(
                not self.full_information
                and should_ask
                and correct_query
                and final_record is not None
                and not final_correct
            ),
            "communication_success": float(
                not self.full_information and should_ask and correct_query and final_correct
            ),
            "post_query_action_correct": float(
                not self.full_information and correct_query and final_correct
            ),
            "stopping_failure": float(not self.full_information and stopping_failure),
            "full_info_action_correct": float(self.full_information and final_correct),
            "final_action_optimal": float(final_correct),
            "num_asks": float(self.query_used),
            "total_decision_regret": sum(record["decision_regret"] for record in self.records),
        }
