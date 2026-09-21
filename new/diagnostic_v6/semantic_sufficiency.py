"""Exact decision-sufficiency certificates for the native semantic B contract.

The deployed judgment gives a support set and either a favored value or
``undetermined``.  It does not give posterior probabilities.  This module
decomposes the compatible posterior set into rational convex polytopes and
checks every vertex with exact arithmetic.  Because action values are affine
in the posterior, agreement at every vertex certifies agreement everywhere in
the polytopes.

We certify the closure of each semantic region: supported probabilities may
approach zero and the favored margin may approach its threshold.  This is a
conservative superset of the posteriors that serialize to the judgment, so a
passing certificate is sufficient even at semantic boundaries.
"""
from fractions import Fraction
from itertools import combinations, permutations


VALUES = ('want', 'neutral', 'avoid')
MARGIN = Fraction(1, 10)
ZERO = Fraction(0)
ONE = Fraction(1)


def _fraction(value):
    result = Fraction(float(value)).limit_denominator(1_000_000)
    if abs(float(result) - float(value)) > 1e-9:
        raise ValueError('Payoff is not stably rationalizable')
    return result


def _solve_three(equations):
    """Return the unique solution of three rational equations, or None."""
    matrix = [[Fraction(value) for value in row] + [Fraction(rhs)]
              for row, rhs in equations]
    for column in range(3):
        pivot = next((row for row in range(column, 3)
                      if matrix[row][column]), None)
        if pivot is None:
            return None
        matrix[column], matrix[pivot] = matrix[pivot], matrix[column]
        scale = matrix[column][column]
        matrix[column] = [value / scale for value in matrix[column]]
        for row in range(3):
            if row == column:
                continue
            scale = matrix[row][column]
            matrix[row] = [left - scale * right
                           for left, right in zip(matrix[row], matrix[column])]
    return tuple(matrix[index][3] for index in range(3))


def _dot(left, right):
    return sum((a * b for a, b in zip(left, right)), ZERO)


def _regions(judgment):
    """Yield closed convex components as (equalities, inequalities, label).

    An inequality is represented as ``coefficients @ p <= rhs``.
    ``undetermined`` is a union over possible probability rankings because its
    rule constrains only the largest and second-largest supported masses.
    """
    support = tuple(VALUES.index(value)
                    for value in judgment['possible_preferences'])
    if not support:
        raise ValueError('A semantic judgment needs nonempty support')
    equalities = [((ONE, ONE, ONE), ONE)]
    for index in range(3):
        if index not in support:
            row = [ZERO] * 3
            row[index] = ONE
            equalities.append((tuple(row), ZERO))
    nonnegative = []
    for index in support:
        row = [ZERO] * 3
        row[index] = -ONE
        nonnegative.append((tuple(row), ZERO))

    favored = judgment['favored']
    if favored != 'undetermined':
        lead = VALUES.index(favored)
        if lead not in support:
            raise ValueError('Favored value is outside semantic support')
        inequalities = list(nonnegative)
        for other in support:
            if other == lead:
                continue
            # p_lead - p_other >= margin.
            row = [ZERO] * 3
            row[other], row[lead] = ONE, -ONE
            inequalities.append((tuple(row), -MARGIN))
        yield equalities, inequalities, 'favored:' + favored
        return

    if len(support) == 1:
        raise ValueError('Singleton semantic support cannot be undetermined')
    for order in permutations(support):
        inequalities = list(nonnegative)
        for high, low in zip(order, order[1:]):
            # p_high >= p_low.
            row = [ZERO] * 3
            row[low], row[high] = ONE, -ONE
            inequalities.append((tuple(row), ZERO))
        # The leading mass is no more than margin above the runner-up.
        row = [ZERO] * 3
        row[order[0]], row[order[1]] = ONE, -ONE
        inequalities.append((tuple(row), MARGIN))
        yield equalities, inequalities, 'ranking:' + '>'.join(
            VALUES[index] for index in order)


def _vertices(equalities, inequalities):
    boundaries = list(equalities) + list(inequalities)
    result = set()
    for selected in combinations(boundaries, 3):
        point = _solve_three(selected)
        if point is None:
            continue
        if any(_dot(row, point) != rhs for row, rhs in equalities):
            continue
        if any(_dot(row, point) > rhs for row, rhs in inequalities):
            continue
        result.add(point)
    if not result:
        raise ValueError('Semantic posterior region has no vertices')
    return tuple(sorted(result))


def _serialize_fraction(value):
    return str(value.numerator) + '/' + str(value.denominator)


def certify(judgment, per_world_payoffs, actor=0):
    """Certify one invariant exact optimal-action set over all compatible B.

    ``per_world_payoffs`` is indexed by action, preference world, and player.
    The returned certificate contains exact rational vertices and action values.
    ``decision_sufficient`` is true only when all vertices in all components
    have exactly the same optimal-action set.
    """
    payoffs = tuple(tuple(_fraction(world[actor]) for world in action)
                    for action in per_world_payoffs)
    if not payoffs or any(len(action) != 3 for action in payoffs):
        raise ValueError('Expected one payoff per native preference value')

    components = []
    observed_sets = set()
    for equalities, inequalities, label in _regions(judgment):
        vertices = _vertices(equalities, inequalities)
        rows = []
        for posterior in vertices:
            action_values = tuple(_dot(action, posterior) for action in payoffs)
            best = max(action_values)
            optimum = tuple(index for index, value in enumerate(action_values)
                            if value == best)
            observed_sets.add(optimum)
            rows.append({
                'posterior': [_serialize_fraction(value) for value in posterior],
                'action_values': [_serialize_fraction(value)
                                  for value in action_values],
                'optimal_action_indices': list(optimum),
            })
        components.append({'region': label, 'vertices': rows})

    stable = len(observed_sets) == 1
    optimum = next(iter(observed_sets)) if stable else ()
    worst_gap = None
    if stable and len(optimum) < len(payoffs):
        outside = set(range(len(payoffs))) - set(optimum)
        margins = []
        for component in components:
            for vertex in component['vertices']:
                values = [Fraction(value) for value in vertex['action_values']]
                margins.extend(values[inside] - values[other]
                               for inside in optimum for other in outside)
        worst_gap = min(margins)
        if worst_gap <= 0:
            raise AssertionError('Stable exact optimum lacks positive separation')

    return {
        'method': 'exact-rational-polytope-vertices-v1',
        'semantic_region': 'closed conservative superset',
        'affine_value_argument': (
            'Action values are affine in the posterior, so exact agreement at '
            'every vertex proves agreement throughout every convex component.'),
        'decision_sufficient': stable,
        'invariant_optimal_action_indices': list(optimum) if stable else None,
        'distinct_vertex_optimal_action_sets': [list(value)
                                                for value in sorted(observed_sets)],
        'worst_exact_optimality_gap': (
            _serialize_fraction(worst_gap) if worst_gap is not None else None),
        'components': components,
    }
