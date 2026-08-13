"""
Evaluation metrics for quantile (interval) forecasts.

This module is the single place that defines how we judge the models. It is pure
numpy with no plotting and no file writing, so it can be imported by the test stage,
the inference build, or a notebook without side effects.

The model outputs three numbers per row (Q10, Q50, Q90), all in percentage points.
The label y is the realized percentage move of the candle. Read Evaluation/README.md
for the plain-language meaning of each metric and why it was chosen.
"""

from __future__ import annotations

import numpy as np

import config

PRED_CLASSES = ["Short", "Stay-out", "Long"]
ACTUAL_CLASSES = ["Below band", "Within band", "Above band"]


def coverage(y: np.ndarray, q_low: np.ndarray, q_high: np.ndarray) -> float:
    """Fraction of realized moves that landed inside the predicted band [Q10, Q90]."""
    y, q_low, q_high = np.asarray(y), np.asarray(q_low), np.asarray(q_high)
    inside = (y >= q_low) & (y <= q_high)
    return float(np.mean(inside))


def mean_band_width(q_low: np.ndarray, q_high: np.ndarray) -> float:
    """Average width of the band (Q90 minus Q10), in percentage points."""
    q_low, q_high = np.asarray(q_low), np.asarray(q_high)
    return float(np.mean(q_high - q_low))


def pinball_loss(y: np.ndarray, pred: np.ndarray, alpha: float) -> float:
    """Pinball (quantile) loss for a single quantile. Lower is better."""
    y, pred = np.asarray(y), np.asarray(pred)
    error = y - pred
    loss = np.where(error >= 0, alpha * error, (alpha - 1.0) * error)
    return float(np.mean(loss))


def q50_errors(y: np.ndarray, q_mid: np.ndarray) -> dict[str, float]:
    """Point-accuracy of the central forecast (Q50): MAE and RMSE in percentage points."""
    y, q_mid = np.asarray(y), np.asarray(q_mid)
    err = y - q_mid
    return {"mae": float(np.mean(np.abs(err))), "rmse": float(np.sqrt(np.mean(err ** 2)))}


def directional_accuracy(y: np.ndarray, q_mid: np.ndarray) -> float:
    """Share of rows where the sign of the central forecast matches the realized sign."""
    y, q_mid = np.asarray(y), np.asarray(q_mid)
    return float(np.mean(np.sign(y) == np.sign(q_mid)))


def interval_score(y: np.ndarray, q_low: np.ndarray, q_high: np.ndarray,
                   nominal_coverage: float) -> float:
    """Winkler interval score for a central prediction interval. Lower is better."""
    y, q_low, q_high = np.asarray(y), np.asarray(q_low), np.asarray(q_high)
    alpha = 1.0 - nominal_coverage
    width = q_high - q_low
    below = (2.0 / alpha) * (q_low - y) * (y < q_low)
    above = (2.0 / alpha) * (y - q_high) * (y > q_high)
    return float(np.mean(width + below + above))


def probability_up(q_low: np.ndarray, q_mid: np.ndarray, q_high: np.ndarray) -> np.ndarray:
    """
    P(next move > 0), read off the three fitted quantiles.

    Q10, Q50 and Q90 are three points on the outcome's cumulative distribution, at
    0.10, 0.50 and 0.90. Interpolating linearly between them gives the distribution's
    value at zero, and one minus that is the chance the move is positive. It is the
    median expressed in units of the band's own width, so a small expected move inside
    a turbulent band scores near a coin flip while the same move inside a calm band
    counts for much more.
    """
    q_low, q_mid, q_high = np.asarray(q_low), np.asarray(q_mid), np.asarray(q_high)
    lower = np.maximum(q_mid - q_low, 1e-9)
    upper = np.maximum(q_high - q_mid, 1e-9)
    below_median = q_mid > 0.0
    cdf_at_zero = np.where(below_median,
                           0.50 - 0.40 * q_mid / lower,
                           0.50 + 0.40 * (-q_mid) / upper)
    return 1.0 - np.clip(cdf_at_zero, 0.0, 1.0)


def fit_recommendation_rule(p_up: np.ndarray, q_mid: np.ndarray, buckets: np.ndarray,
                            rate: float | None = None,
                            min_move_percentile: float | None = None) -> dict:
    """
    Measure the rule that turns a band into a direction, from the model's own output.

    Two gates, fitted together:

    A **move floor** on the median's magnitude. Late in a candle the band is narrow and
    the model is confident about a move far too small to act on; left alone, those rows
    take over the calls. The floor is a percentile of the median's own historical size,
    so it is measured rather than asserted and grows with the history.

    A **margin** either side of a coin flip on P(move > 0), fitted separately per
    position bucket. The spread of P(up) widens as a candle nears its close, purely
    because the band tightens, so a single margin would hand out most of its calls at
    the end of the candle and almost none at the start. One margin per bucket keeps the
    rate of calls steady across the candle, and lets each stretch answer for itself.

    The margin is symmetric about 0.5, so nothing forces Long and Short to appear in
    equal numbers - a horizon that drifts upward will produce mostly Longs, which is the
    finding rather than a bias to correct.
    """
    rate = 0.0 if rate is None else rate
    pct = 0.0 if min_move_percentile is None else min_move_percentile
    p_up, q_mid = np.asarray(p_up, dtype=float), np.asarray(q_mid, dtype=float)
    buckets = np.asarray(buckets, dtype=int)

    if rate <= 0:
        return {"move_floor": np.inf, "margins": [np.inf], "rate": rate}

    move_floor = float(np.quantile(np.abs(q_mid), pct)) if pct > 0 else 0.0
    eligible = np.abs(q_mid) >= move_floor
    distance = np.abs(p_up - 0.5)

    margins = []
    for b in range(int(buckets.max()) + 1 if buckets.size else 1):
        in_bucket = buckets == b
        pool = distance[in_bucket & eligible]
        wanted = rate * float(in_bucket.sum())
        if pool.size == 0 or wanted <= 0:
            margins.append(float("inf"))
        elif wanted >= pool.size:
            margins.append(0.0)          # every eligible row in this bucket may fire
        else:
            margins.append(float(np.quantile(pool, 1.0 - wanted / pool.size)))
    return {"move_floor": move_floor, "margins": margins, "rate": rate}


def apply_recommendation_rule(p_up: np.ndarray, q_mid: np.ndarray,
                              buckets: np.ndarray, rule: dict | None) -> np.ndarray:
    """Turn probabilities into calls. 0 Short, 1 Stay-out, 2 Long. Without a rule every
    row is Stay-out, which is the correct answer when nothing has established what a
    directional setup looks like for this model."""
    p_up, q_mid = np.asarray(p_up, dtype=float), np.asarray(q_mid, dtype=float)
    codes = np.ones(p_up.shape, dtype=int)
    if not rule:
        return codes

    margins = np.asarray(rule["margins"], dtype=float)
    buckets = np.clip(np.asarray(buckets, dtype=int), 0, margins.size - 1)
    margin = margins[buckets]

    allowed = (np.abs(q_mid) >= rule["move_floor"]) & np.isfinite(margin)
    codes[allowed & (p_up >= 0.5 + margin)] = 2
    codes[allowed & (p_up <= 0.5 - margin)] = 0
    return codes


def actual_band_class(y: np.ndarray, q_low: np.ndarray, q_high: np.ndarray) -> np.ndarray:
    """Classify each realized move relative to the band. 0 below, 1 within, 2 above."""
    y, q_low, q_high = np.asarray(y), np.asarray(q_low), np.asarray(q_high)
    codes = np.full(y.shape, 1, dtype=int)
    codes[y < q_low] = 0
    codes[y > q_high] = 2
    return codes


def directional_confusion_matrix(y: np.ndarray, q_low: np.ndarray, q_high: np.ndarray,
                                 codes: np.ndarray) -> np.ndarray:
    """3x3 confusion matrix of predicted recommendation against realized outcome."""
    pred = np.asarray(codes)
    actual = actual_band_class(y, q_low, q_high)
    matrix = np.zeros((3, 3), dtype=int)
    for p, a in zip(pred, actual):
        matrix[p, a] += 1
    return matrix


def confusion_accuracy(matrix: np.ndarray) -> float:
    """Diagonal sum over total."""
    total = matrix.sum()
    return float(np.trace(matrix) / total) if total else 0.0


def evaluate_all(y: np.ndarray, q_low: np.ndarray, q_mid: np.ndarray,
                 q_high: np.ndarray, nominal_coverage: float,
                 alphas: dict[str, float], codes=None) -> dict[str, float]:
    """Run every scalar metric at once and return a flat dictionary."""
    errors = q50_errors(y, q_mid)
    return {
        "n_samples": int(len(y)),
        "coverage": coverage(y, q_low, q_high),
        "nominal_coverage": float(nominal_coverage),
        "mean_band_width": mean_band_width(q_low, q_high),
        "interval_score": interval_score(y, q_low, q_high, nominal_coverage),
        "pinball_q10": pinball_loss(y, q_low, alphas["q10"]),
        "pinball_q50": pinball_loss(y, q_mid, alphas["q50"]),
        "pinball_q90": pinball_loss(y, q_high, alphas["q90"]),
        "q50_mae": errors["mae"],
        "q50_rmse": errors["rmse"],
        "directional_accuracy": directional_accuracy(y, q_mid),
        "confusion_accuracy": confusion_accuracy(
            directional_confusion_matrix(y, q_low, q_high, codes)
        ) if codes is not None else float("nan"),
        "recommendation_rate": float(np.mean(np.asarray(codes) != 1))
        if codes is not None else float("nan"),
        "recommendation_hit_rate": recommendation_hit_rate(y, codes)
        if codes is not None else float("nan"),
    }


def recommendation_hit_rate(y: np.ndarray, codes: np.ndarray) -> float:
    """Of the rows where a direction was named, the share that moved that way. This is
    the number that decides whether the recommendation is worth showing at all; a value
    near 0.5 means the call carries no information no matter how often it fires."""
    codes = np.asarray(codes)
    fired = codes != 1
    if not fired.any():
        return float("nan")
    went_up = np.asarray(y) > 0
    correct = ((codes == 2) & went_up) | ((codes == 0) & ~went_up)
    return float(correct[fired].sum() / fired.sum())


# Rates on a fine grid, and floors across the range of MIN_MOVE_PERCENTILE. Both are
# swept because either can be the binding constraint: raising the rate stops doing
# anything once every row above the floor already fires, and from that point on only
# the floor decides. A grid over both is the only way to see which one is in charge.
SWEEP_RATES = tuple(round(0.05 * i, 2) for i in range(1, 21))
SWEEP_FLOORS = (0.0, 0.25, 0.50, 0.65, 0.75, 0.85, 0.95)


def recommendation_sweep(y: np.ndarray, p_up: np.ndarray, q_mid: np.ndarray,
                         buckets: np.ndarray, ref_p_up: np.ndarray, ref_mid: np.ndarray,
                         ref_buckets: np.ndarray, rates=SWEEP_RATES,
                         floors=SWEEP_FLOORS) -> list[dict]:
    """
    Hit rate at every candidate recommendation rate, so the rate is chosen by reading a
    curve rather than by guessing a number. The rule is refitted on the reference data
    at each rate and applied to the evaluation data, exactly as production would.

    The trade-off it exposes is the whole decision: a small rate names a direction only
    on the most extreme setups and should score highest, a large rate names one almost
    always and must drift toward the base rate of up moves. A curve that stays flat at
    0.5 across every rate says the ranking carries no directional information, and that
    no choice of rate will rescue it.
    """
    y = np.asarray(y)
    rows = []
    for floor_pct in floors:
        for rate in rates:
            rule = fit_recommendation_rule(ref_p_up, ref_mid, ref_buckets, rate, floor_pct)
            codes = apply_recommendation_rule(p_up, q_mid, buckets, rule)
            fired = codes != 1
            rows.append({
                "min_move_percentile": floor_pct,
                "rate": rate,
                "move_floor": rule["move_floor"],
                "fired_share": float(fired.mean()),
                "n_long": int((codes == 2).sum()),
                "n_short": int((codes == 0).sum()),
                "hit_rate": recommendation_hit_rate(y, codes),
            })

    # Edge: the share of ALL rows that are correct calls beyond what a coin flip would
    # give. Naming a direction on 5% of rows at a hit rate of 0.56 is worth less in
    # total than naming one on 30% at 0.55, and hit rate alone cannot say so - it always
    # rewards being more selective, all the way down to never calling anything at all.
    for row in rows:
        hit = row["hit_rate"]
        row["edge"] = 0.0 if not np.isfinite(hit) else row["fired_share"] * (hit - 0.5)
    best = max(rows, key=lambda r: r["edge"])
    for row in rows:
        row["best_by_edge"] = row is best
    return rows


def coverage_breakdown(y: np.ndarray, q_low: np.ndarray, q_high: np.ndarray,
                       by: np.ndarray) -> list[dict]:
    """Coverage and mean band width per slice of the data."""
    y, q_low, q_high, by = (np.asarray(y), np.asarray(q_low),
                            np.asarray(q_high), np.asarray(by))
    rows = []
    for value in pd_unique(by):
        mask = by == value
        if not mask.any():
            continue
        rows.append({
            "slice": str(value),
            "n": int(mask.sum()),
            "coverage": coverage(y[mask], q_low[mask], q_high[mask]),
            "mean_band_width": mean_band_width(q_low[mask], q_high[mask]),
        })
    return rows


def pd_unique(values: np.ndarray) -> list:
    """Stable-ordered unique values without importing pandas here."""
    seen, out = set(), []
    for v in values:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out