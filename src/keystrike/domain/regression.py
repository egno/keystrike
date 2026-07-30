"""Learning-rate regression: fit a polynomial to a key's recent per-attempt
timings and estimate how many more attempts until it crosses the target time.

No numpy (deps are locked, see PLAN.md §1) — polynomial least-squares via the
normal equations, solved with Gaussian elimination. Degree scales with how
much data we have: linear for <=10 samples, quadratic for 11-20, cubic for
>20, capped at the last 30 samples.
"""

from __future__ import annotations

from collections.abc import Sequence

MAX_SAMPLES = 30
_LINEAR_MAX = 10
_QUADRATIC_MAX = 20
_MAX_LOOKAHEAD = 100
_MIN_SAMPLES_TO_FIT = 2
_SINGULAR_EPSILON = 1e-12


def _degree_for(sample_count: int) -> int:
    if sample_count <= _LINEAR_MAX:
        return 1
    if sample_count <= _QUADRATIC_MAX:
        return 2
    return 3


def estimate_sessions_to_goal(
    recent_time_ns: Sequence[float],
    target_time_ns: float,
) -> int | None:
    """`recent_time_ns` is per-attempt time, oldest first (most recent 30 kept).

    Returns the number of additional attempts, at the observed trend, until
    the fitted curve reaches `target_time_ns` — or None if there isn't enough
    data to fit, the trend is flat/worsening, or the goal isn't reached within
    a reasonable lookahead.
    """
    samples = list(recent_time_ns[-MAX_SAMPLES:])
    if len(samples) < _MIN_SAMPLES_TO_FIT:
        return None
    if samples[-1] <= target_time_ns:
        return 0

    degree = min(_degree_for(len(samples)), len(samples) - 1)
    xs = list(range(len(samples)))
    try:
        coeffs = _polyfit(xs, samples, degree)
    except ValueError:
        return None

    last_x = len(samples) - 1
    for lookahead in range(1, _MAX_LOOKAHEAD + 1):
        if _polyval(coeffs, last_x + lookahead) <= target_time_ns:
            return lookahead
    return None


def _polyval(coeffs_high_to_low: Sequence[float], x: float) -> float:
    result = 0.0
    for c in coeffs_high_to_low:
        result = result * x + c
    return result


def _polyfit(xs: Sequence[float], ys: Sequence[float], degree: int) -> list[float]:
    """Least-squares fit; returns coefficients highest-degree-first."""
    n = degree + 1
    powers_sum = [sum(x**k for x in xs) for k in range(2 * degree + 1)]
    matrix = [[powers_sum[i + j] for j in range(n)] for i in range(n)]
    rhs = [sum((x**i) * y for x, y in zip(xs, ys, strict=True)) for i in range(n)]
    coeffs_low_to_high = _solve_linear_system(matrix, rhs)
    return list(reversed(coeffs_low_to_high))


def _solve_linear_system(matrix: list[list[float]], rhs: list[float]) -> list[float]:
    """Gaussian elimination with partial pivoting for a small (<=4x4) system."""
    n = len(rhs)
    augmented = [[*row, rhs[i]] for i, row in enumerate(matrix)]

    for col in range(n):
        pivot_row = max(range(col, n), key=lambda r: abs(augmented[r][col]))
        augmented[col], augmented[pivot_row] = augmented[pivot_row], augmented[col]
        pivot = augmented[col][col]
        if abs(pivot) < _SINGULAR_EPSILON:
            raise ValueError("singular matrix in polynomial fit")
        for row in range(col + 1, n):
            factor = augmented[row][col] / pivot
            for k in range(col, n + 1):
                augmented[row][k] -= factor * augmented[col][k]

    solution = [0.0] * n
    for row in range(n - 1, -1, -1):
        known = sum(augmented[row][k] * solution[k] for k in range(row + 1, n))
        solution[row] = (augmented[row][n] - known) / augmented[row][row]
    return solution
