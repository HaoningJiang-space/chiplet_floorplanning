"""Descriptive orthogonal decomposition of a complete balanced factorial."""

import itertools

import numpy as np


def factorial_decomposition(coordinates, values, factor_names):
    coordinates = [tuple(row) for row in coordinates]
    values = np.asarray(values, dtype=float)
    if (
        not coordinates
        or len(coordinates) != len(values)
        or any(len(c) != len(factor_names) for c in coordinates)
        or len(set(factor_names)) != len(factor_names)
        or not factor_names
        or not np.all(np.isfinite(values))
    ):
        raise ValueError("invalid factorial observations")
    levels = [sorted({c[i] for c in coordinates}) for i in range(len(factor_names))]
    grid = list(itertools.product(*levels))
    if len(set(coordinates)) != len(coordinates) or set(coordinates) != set(grid):
        raise ValueError("factorial requires one observation per complete cell")
    lookup = dict(zip(coordinates, values))
    array = np.asarray([lookup[c] for c in grid]).reshape(tuple(map(len, levels)))
    grand = float(array.mean())
    effects = {(): np.full((1,) * array.ndim, grand)}
    terms = {}
    for size in range(1, array.ndim + 1):
        for subset in itertools.combinations(range(array.ndim), size):
            other = tuple(i for i in range(array.ndim) if i not in subset)
            effect = array.mean(axis=other, keepdims=True) if other else array.copy()
            for previous, value in effects.items():
                if set(previous) < set(subset):
                    effect = effect - value
            effects[subset] = effect
            ss = float(np.sum(np.broadcast_to(effect, array.shape) ** 2))
            terms[":".join(factor_names[i] for i in subset)] = dict(
                sum_squares_k2=ss, order=size
            )
    total = float(np.sum((array - grand) ** 2))
    closure = abs(sum(t["sum_squares_k2"] for t in terms.values()) - total)
    if closure > 1e-10 * max(1.0, total):
        raise ValueError("factorial sum of squares does not close")
    for term in terms.values():
        term["fraction_of_total"] = term["sum_squares_k2"] / total if total else None
    return dict(
        grand_mean_k=grand,
        total_sum_squares_k2=total,
        terms=terms,
        sum_squares_closure_error_k2=closure,
        main_effect_fraction=(
            sum(t["sum_squares_k2"] for t in terms.values() if t["order"] == 1) / total
            if total
            else None
        ),
        scope="descriptive deterministic factorial; no causal shares, p-values or independent replicates",
    )
