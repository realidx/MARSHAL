"""Immutable game objects and seeded procedural DAG generation."""

from __future__ import annotations

from dataclasses import dataclass, replace
from functools import lru_cache
import hashlib
import json
import random
from typing import Dict, Iterable, Optional, Tuple

from .solver import GeographySolution, solve_geography, topological_order


@dataclass(frozen=True)
class GeographyGraph:
    adjacency: Tuple[Tuple[int, ...], ...]
    labels: Tuple[str, ...]
    start_node: int
    episode_seed: int
    graph_id: str
    display_order: Tuple[int, ...]

    def __post_init__(self) -> None:
        node_count = len(self.adjacency)
        if node_count == 0:
            raise ValueError("Geography graph must contain at least one node")
        if len(self.labels) != node_count or len(set(self.labels)) != node_count:
            raise ValueError("Geography node labels must be unique and complete")
        if tuple(sorted(self.display_order)) != tuple(range(node_count)):
            raise ValueError("display_order must contain every node exactly once")
        if not 0 <= self.start_node < node_count:
            raise ValueError("start_node is outside the graph")
        for node, successors in enumerate(self.adjacency):
            if len(set(successors)) != len(successors):
                raise ValueError(f"Node {node} contains duplicate outgoing edges")
            if any(child < 0 or child >= node_count for child in successors):
                raise ValueError(f"Node {node} contains an invalid successor")
        topological_order(self.adjacency)
        if self.reachable_nodes() != frozenset(range(node_count)):
            raise ValueError("Every Geography node must be reachable from the root")

    @property
    def num_nodes(self) -> int:
        return len(self.adjacency)

    @property
    def num_edges(self) -> int:
        return sum(len(successors) for successors in self.adjacency)

    def reachable_nodes(self) -> frozenset[int]:
        seen = set()
        stack = [self.start_node]
        while stack:
            node = stack.pop()
            if node in seen:
                continue
            seen.add(node)
            stack.extend(self.adjacency[node])
        return frozenset(seen)

    def render(self) -> str:
        lines = []
        for node in self.display_order:
            successors = self.adjacency[node]
            rendered = ", ".join(self.labels[child] for child in successors)
            lines.append(f"{self.labels[node]} -> {rendered if rendered else 'terminal'}")
        return "\n".join(lines)

    def relabel(self, seed: int) -> "GeographyGraph":
        rng = random.Random(seed)
        labels = [f"N{index}" for index in range(self.num_nodes)]
        rng.shuffle(labels)
        display_order = list(range(self.num_nodes))
        rng.shuffle(display_order)
        adjacency = [list(successors) for successors in self.adjacency]
        for successors in adjacency:
            rng.shuffle(successors)
        return GeographyGraph(
            adjacency=tuple(tuple(successors) for successors in adjacency),
            labels=tuple(labels),
            start_node=self.start_node,
            episode_seed=self.episode_seed,
            graph_id=_graph_identifier(adjacency, self.start_node),
            display_order=tuple(display_order),
        )


@dataclass(frozen=True)
class GeographyState:
    graph: GeographyGraph
    current_node: int
    player_to_act: int = 0
    move_history: Tuple[int, ...] = ()

    def legal_actions(self) -> Tuple[int, ...]:
        return self.graph.adjacency[self.current_node]

    def is_terminal(self) -> bool:
        return not self.legal_actions()

    def current_player(self) -> int:
        return self.player_to_act

    def apply_action(self, action: int) -> "GeographyState":
        if action not in self.legal_actions():
            raise ValueError(
                f"{self.graph.labels[action] if 0 <= action < self.graph.num_nodes else action!r} "
                f"is not legal from {self.graph.labels[self.current_node]}"
            )
        return replace(
            self,
            current_node=action,
            player_to_act=1 - self.player_to_act,
            move_history=self.move_history + (action,),
        )

    def render(self) -> str:
        return self.graph.render()


@dataclass(frozen=True)
class GraphProperties:
    root_value: int
    informative_fraction: float
    longest_depth: int
    transposition_rate: float
    mean_branching: float


def graph_properties(graph: GeographyGraph, solution: GeographySolution) -> GraphProperties:
    depths = [-1] * graph.num_nodes
    depths[graph.start_node] = 0
    for node in solution.topological_order:
        if depths[node] < 0:
            continue
        for child in graph.adjacency[node]:
            depths[child] = max(depths[child], depths[node] + 1)
    nonterminal = [node for node, successors in enumerate(graph.adjacency) if successors]
    informative = [node for node in nonterminal if solution.decision_spreads[node] > 0]
    indegrees = [0] * graph.num_nodes
    for successors in graph.adjacency:
        for child in successors:
            indegrees[child] += 1
    return GraphProperties(
        root_value=solution.value(graph.start_node),
        informative_fraction=len(informative) / len(nonterminal) if nonterminal else 0.0,
        longest_depth=max(depths),
        transposition_rate=(
            sum(degree > 1 for degree in indegrees[1:]) / (graph.num_nodes - 1)
            if graph.num_nodes > 1
            else 0.0
        ),
        mean_branching=(
            sum(len(graph.adjacency[node]) for node in nonterminal) / len(nonterminal)
            if nonterminal
            else 0.0
        ),
    )


@lru_cache(maxsize=4096)
def generate_geography_graph(
    *,
    seed: int,
    num_nodes: int,
    min_depth: int,
    max_depth: int,
    min_branching: int,
    max_branching: int,
    transposition_rate: float,
    target_root_value: Optional[int] = None,
    target_root_informative: Optional[bool] = None,
    target_root_optimal_distance: Optional[int] = None,
    target_root_branching: Optional[int] = None,
    target_informative_fraction: Optional[float] = None,
    candidate_count: int = 32,
) -> Tuple[GeographyGraph, GeographySolution, GraphProperties]:
    _validate_generator_args(
        num_nodes,
        min_depth,
        max_depth,
        min_branching,
        max_branching,
        transposition_rate,
        target_root_value,
        target_root_informative,
        target_root_optimal_distance,
        target_root_branching,
        target_informative_fraction,
        candidate_count,
    )
    candidates = []
    for candidate_index in range(candidate_count):
        candidate_seed = _derived_seed(seed, candidate_index)
        graph = _generate_candidate(
            candidate_seed,
            num_nodes,
            min_depth,
            max_depth,
            min_branching,
            max_branching,
            transposition_rate,
        )
        solution = solve_geography(graph.adjacency)
        properties = graph_properties(graph, solution)
        score = abs(properties.transposition_rate - transposition_rate)
        if target_root_value is not None:
            score += 2.0 * float(properties.root_value != target_root_value)
        if target_root_informative is not None:
            root_is_informative = solution.decision_spreads[graph.start_node] > 0
            score += 2.0 * float(root_is_informative != target_root_informative)
        if target_root_optimal_distance is not None:
            score += abs(
                solution.optimal_distances[graph.start_node]
                - target_root_optimal_distance
            )
        if target_root_branching is not None:
            score += abs(len(graph.adjacency[graph.start_node]) - target_root_branching)
        if target_informative_fraction is not None:
            score += abs(properties.informative_fraction - target_informative_fraction)
        candidates.append((score, candidate_index, graph, solution, properties))

    # Exact distance is an experimental stratum, not a soft preference. When
    # requested, also enforce the paired root branching/informativeness controls
    # so graph size or an all-actions-equal root cannot redefine the stratum.
    if target_root_optimal_distance is not None:
        exact_candidates = [
            item
            for item in candidates
            if item[3].optimal_distances[item[2].start_node]
            == target_root_optimal_distance
            and (
                target_root_branching is None
                or len(item[2].adjacency[item[2].start_node])
                == target_root_branching
            )
            and (
                target_root_informative is None
                or (item[3].decision_spreads[item[2].start_node] > 0)
                == target_root_informative
            )
        ]
        if not exact_candidates:
            raise ValueError(
                "No graph matched target_root_optimal_distance="
                f"{target_root_optimal_distance} and target_root_branching="
                f"{target_root_branching} among {candidate_count} candidates"
            )
        candidates = exact_candidates

    _, _, graph, solution, properties = min(
        candidates, key=lambda item: (item[0], item[1])
    )
    graph = replace(graph, episode_seed=seed)
    return graph, solution, properties


def _generate_candidate(
    seed: int,
    num_nodes: int,
    min_depth: int,
    max_depth: int,
    min_branching: int,
    max_branching: int,
    transposition_rate: float,
) -> GeographyGraph:
    rng = random.Random(seed)
    adjacency = [set() for _ in range(num_nodes)]
    depths = [0] * num_nodes
    first_reserved_leaf = num_nodes - min_branching

    # A backbone guarantees the requested minimum root-to-node depth.
    for node in range(1, min_depth + 1):
        adjacency[node - 1].add(node)
        depths[node] = node

    # Attach remaining nodes once to guarantee root reachability. Edges always
    # point from a lower internal id to a higher one, which guarantees a DAG.
    for node in range(min_depth + 1, num_nodes):
        parents = [
            parent
            for parent in range(min(node, first_reserved_leaf))
            if depths[parent] < max_depth and len(adjacency[parent]) < max_branching
        ]
        if not parents:
            raise ValueError("Generator constraints leave no parent capacity")
        parent = rng.choice(parents)
        adjacency[parent].add(node)
        depths[node] = depths[parent] + 1

    # The final min_branching nodes are reserved as leaves. They provide enough
    # shared successors to make the lower branching bound exact for every
    # nonterminal node without risking a path deeper than max_depth.
    reserved_leaves = tuple(range(first_reserved_leaf, num_nodes))
    for node in range(first_reserved_leaf):
        if not adjacency[node]:
            continue
        eligible = [
            child
            for child in reserved_leaves
            if child not in adjacency[node]
        ]
        rng.shuffle(eligible)
        while len(adjacency[node]) < min_branching and eligible:
            child = eligible.pop()
            adjacency[node].add(child)
            depths[child] = max(depths[child], depths[node] + 1)

    # Add incoming edges to distinct nodes to approach the requested fraction
    # of transposed nodes, while respecting the outgoing branching cap.
    indegrees = [0] * num_nodes
    for successors in adjacency:
        for child in successors:
            indegrees[child] += 1
    desired = round(transposition_rate * max(0, num_nodes - 1))
    children = list(range(1, num_nodes))
    rng.shuffle(children)
    for child in children:
        if sum(degree > 1 for degree in indegrees[1:]) >= desired:
            break
        if indegrees[child] > 1:
            continue
        parents = [
            parent
            for parent in range(min(child, first_reserved_leaf))
            if child not in adjacency[parent]
            and adjacency[parent]
            and len(adjacency[parent]) < max_branching
            and depths[parent] < depths[child]
        ]
        if parents:
            parent = rng.choice(parents)
            adjacency[parent].add(child)
            indegrees[child] += 1

    labels = [f"N{index}" for index in range(num_nodes)]
    rng.shuffle(labels)
    display_order = list(range(num_nodes))
    rng.shuffle(display_order)
    ordered_adjacency = []
    for successors in adjacency:
        ordered = list(successors)
        rng.shuffle(ordered)
        ordered_adjacency.append(tuple(ordered))
    frozen_adjacency = tuple(ordered_adjacency)
    return GeographyGraph(
        adjacency=frozen_adjacency,
        labels=tuple(labels),
        start_node=0,
        episode_seed=seed,
        graph_id=_graph_identifier(frozen_adjacency, 0),
        display_order=tuple(display_order),
    )


def _graph_identifier(adjacency: Iterable[Iterable[int]], start_node: int) -> str:
    payload = json.dumps(
        {"adjacency": [sorted(row) for row in adjacency], "start": start_node},
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _derived_seed(seed: int, candidate_index: int) -> int:
    payload = f"{seed}:{candidate_index}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


def _validate_generator_args(
    num_nodes: int,
    min_depth: int,
    max_depth: int,
    min_branching: int,
    max_branching: int,
    transposition_rate: float,
    target_root_value: Optional[int],
    target_root_informative: Optional[bool],
    target_root_optimal_distance: Optional[int],
    target_root_branching: Optional[int],
    target_informative_fraction: Optional[float],
    candidate_count: int,
) -> None:
    if num_nodes < 2:
        raise ValueError("num_nodes must be at least two")
    if not 1 <= min_depth <= max_depth < num_nodes:
        raise ValueError("depths must satisfy 1 <= min_depth <= max_depth < num_nodes")
    if not 1 <= min_branching <= max_branching:
        raise ValueError("branching must satisfy 1 <= min_branching <= max_branching")
    if min_depth > num_nodes - min_branching:
        raise ValueError(
            "num_nodes must leave min_branching terminal leaves beyond the depth backbone"
        )
    if not 0.0 <= transposition_rate <= 1.0:
        raise ValueError("transposition_rate must lie in [0, 1]")
    if target_root_value not in (None, -1, 1):
        raise ValueError("target_root_value must be None, -1, or 1")
    if target_root_informative not in (None, False, True):
        raise ValueError("target_root_informative must be None or a boolean")
    if target_root_optimal_distance is not None and not (
        1 <= target_root_optimal_distance <= max_depth
    ):
        raise ValueError(
            "target_root_optimal_distance must lie between 1 and max_depth"
        )
    if target_root_branching is not None and not (
        min_branching <= target_root_branching <= max_branching
    ):
        raise ValueError(
            "target_root_branching must lie within the branching bounds"
        )
    if target_informative_fraction is not None and not 0.0 <= target_informative_fraction <= 1.0:
        raise ValueError("target_informative_fraction must lie in [0, 1]")
    if candidate_count < 1:
        raise ValueError("candidate_count must be positive")
