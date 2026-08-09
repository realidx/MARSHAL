"""Exact reverse-topological solver for DAG Vertex Geography."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Tuple


def topological_order(adjacency: Tuple[Tuple[int, ...], ...]) -> Tuple[int, ...]:
    indegree = [0] * len(adjacency)
    for successors in adjacency:
        for child in successors:
            indegree[child] += 1

    ready = [node for node, degree in enumerate(indegree) if degree == 0]
    order = []
    while ready:
        node = ready.pop()
        order.append(node)
        for child in adjacency[node]:
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)
    if len(order) != len(adjacency):
        raise ValueError("Geography graph must be acyclic")
    return tuple(order)


@dataclass(frozen=True)
class GeographySolution:
    values: Tuple[int, ...]
    q_values: Tuple[Tuple[Tuple[int, int], ...], ...]
    optimal_actions: Tuple[Tuple[int, ...], ...]
    decision_spreads: Tuple[int, ...]
    regrets: Tuple[Tuple[Tuple[int, int], ...], ...]
    optimal_distances: Tuple[int, ...]
    topological_order: Tuple[int, ...]

    def value(self, node: int) -> int:
        return self.values[node]

    def action_values(self, node: int) -> Dict[int, int]:
        return dict(self.q_values[node])

    def action_value(self, node: int, action: int) -> int:
        try:
            return dict(self.q_values[node])[action]
        except KeyError as exc:
            raise ValueError(f"Node {action} is not a legal successor of {node}") from exc

    def regret(self, node: int, action: int) -> int:
        try:
            return dict(self.regrets[node])[action]
        except KeyError as exc:
            raise ValueError(f"Node {action} is not a legal successor of {node}") from exc


def solve_geography(adjacency: Iterable[Iterable[int]]) -> GeographySolution:
    frozen = tuple(tuple(successors) for successors in adjacency)
    order = topological_order(frozen)
    values = [-1] * len(frozen)
    q_values = [dict() for _ in frozen]
    optimal_actions = [tuple() for _ in frozen]
    decision_spreads = [0] * len(frozen)
    regrets = [dict() for _ in frozen]
    optimal_distances = [0] * len(frozen)

    for node in reversed(order):
        successors = frozen[node]
        if not successors:
            values[node] = -1
            continue

        node_q = {child: -values[child] for child in successors}
        best = max(node_q.values())
        optimal = tuple(child for child in successors if node_q[child] == best)
        spread = best - min(node_q.values())

        q_values[node] = node_q
        values[node] = best
        optimal_actions[node] = optimal
        decision_spreads[node] = spread
        regrets[node] = {child: best - q for child, q in node_q.items()}
        # Delta=1 does not rank equally valued continuations by speed. This
        # shortest-optimal-line convention is diagnostic only.
        optimal_distances[node] = 1 + min(optimal_distances[child] for child in optimal)

    return GeographySolution(
        values=tuple(values),
        q_values=tuple(tuple(items.items()) for items in q_values),
        optimal_actions=tuple(optimal_actions),
        decision_spreads=tuple(decision_spreads),
        regrets=tuple(tuple(items.items()) for items in regrets),
        optimal_distances=tuple(optimal_distances),
        topological_order=order,
    )

