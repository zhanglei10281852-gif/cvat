"""Minimal shim of scipy.optimize.linear_sum_assignment for offline tests."""

import numpy as np


def linear_sum_assignment(cost_matrix):
    cost = np.asarray(cost_matrix, dtype=float)
    if cost.ndim != 2 or cost.size == 0:
        raise ValueError("cost_matrix must be a non-empty 2D array")

    n_rows, n_cols = cost.shape
    padded = np.pad(
        cost,
        (
            (0, max(n_cols - n_rows, 0)),
            (0, max(n_rows - n_cols, 0)),
        ),
        mode="constant",
        constant_values=float(np.nanmax(cost)) + 1.0,
    )
    n = padded.shape[0]
    u = np.zeros(n + 1)
    v = np.zeros(n + 1)
    p = np.zeros(n + 1, dtype=int)
    way = np.zeros(n + 1, dtype=int)

    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = np.full(n + 1, np.inf)
        used = np.zeros(n + 1, dtype=bool)

        while True:
            used[j0] = True
            i0 = p[j0]
            delta = np.inf
            j1 = 0
            for j in range(1, n + 1):
                if not used[j]:
                    cur = padded[i0 - 1, j - 1] - u[i0] - v[j]
                    if cur < minv[j]:
                        minv[j] = cur
                        way[j] = j0
                    if minv[j] < delta:
                        delta = minv[j]
                        j1 = j

            for j in range(n + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta

            j0 = j1
            if p[j0] == 0:
                break

        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break

    rows = []
    cols = []
    for j in range(1, n + 1):
        i = p[j]
        if i <= n_rows and j <= n_cols:
            rows.append(i - 1)
            cols.append(j - 1)

    return np.array(rows), np.array(cols)
