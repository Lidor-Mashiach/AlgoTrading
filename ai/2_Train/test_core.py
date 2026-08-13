"""
Test core.

Shared evaluation engine called once per horizon. It loads the three development boosters,
predicts Q10, Q50, and Q90 on the held-out test split, computes every metric from the
Evaluation module, and writes the numbers and figures into the categorized results tree:
plots for figures, metrics for numbers, reports for the readable summary.

Coverage is the headline number, always read together with the mean band width.
"""

from __future__ import annotations

# --- make the ai/ root importable regardless of where this script is launched from ---
import sys
import pathlib

for _parent in pathlib.Path(__file__).resolve().parents:
    if (_parent / "config.py").exists() and (_parent / "utils").is_dir():
        if str(_parent) not in sys.path:
            sys.path.insert(0, str(_parent))
        break

import json

import numpy as np
import pandas as pd

import config
from utils.log import log
from utils import io_store, plotting, modeling
from Evaluation import metrics

# ----------------------------------------------------------------------------------
# GLOBAL PARAMETERS
# ----------------------------------------------------------------------------------
MAX_INTERVAL_POINTS = 300   # cap on points drawn in the interval chart, for readability


def load_calibration(horizon: str) -> dict:
    """The per-bucket conformal offsets the train stage measured on held-out recent
    candles. A flat zero when absent, which scores the raw band rather than failing."""
    path = (config.RESULTS_ROOT / "metrics" / f"train_{horizon}" / "calibration"
            / "calibration.json")
    if path.exists():
        return json.loads(path.read_text())
    return {"offsets": [0.0], "bucket_edges": None}


def load_boosters(horizon: str) -> dict:
    """Load the three development boosters for a horizon from dev_models/."""
    import lightgbm as lgb

    boosters = {}
    for qname in config.QUANTILES:
        path = config.dev_model_path(horizon, qname)
        if not path.exists():
            raise FileNotFoundError(
                f"Missing development booster {path}. Run train_{horizon}.py first."
            )
        boosters[qname] = lgb.Booster(model_file=str(path))
    return boosters


def predict_quantiles(boosters: dict, X) -> dict:
    """Predict every quantile on the feature frame, returned as name -> array."""
    return {qname: boosters[qname].predict(X) for qname in config.QUANTILES}


# ----------------------------------------------------------------------------------
# Figures
# ----------------------------------------------------------------------------------
def plot_interval(y, q_low, q_mid, q_high, out_path: pathlib.Path) -> None:
    """Band [Q10, Q90] with the median and the realized move, ordered by realized move."""
    order = np.argsort(y)
    if len(order) > MAX_INTERVAL_POINTS:
        order = order[np.linspace(0, len(order) - 1, MAX_INTERVAL_POINTS).astype(int)]
    x = np.arange(len(order))

    fig, ax = plotting.new_axes(9.0, 5.0)
    ax.fill_between(x, q_low[order], q_high[order], color="#9ecae1", alpha=0.6,
                    label="Q10-Q90 band")
    ax.plot(x, q_mid[order], color="#08519c", linewidth=1.0, label="Q50")
    ax.scatter(x, y[order], s=8, color="#d94701", label="realized", zorder=3)
    ax.axhline(0.0, color="grey", linewidth=0.8, linestyle="--")
    ax.set_xlabel("test samples (ordered by realized move)")
    ax.set_ylabel("percent move")
    ax.set_title("Predicted interval vs realized move")
    ax.legend(loc="upper left", fontsize=8)
    plotting.save_and_close(fig, out_path)


def plot_confusion(matrix: np.ndarray, out_path: pathlib.Path) -> None:
    """Annotated 3x3 confusion matrix of predicted recommendation vs realized outcome."""
    fig, ax = plotting.new_axes(6.0, 5.0)
    ax.imshow(matrix, cmap=plotting.BLUE_WHITE)
    ax.set_xticks(range(3))
    ax.set_yticks(range(3))
    ax.set_xticklabels(metrics.ACTUAL_CLASSES, fontsize=9)
    ax.set_yticklabels(metrics.PRED_CLASSES, fontsize=9)
    ax.set_xlabel("realized outcome")
    ax.set_ylabel("predicted recommendation")
    ax.set_title("Directional confusion matrix")
    threshold = matrix.max() / 2 if matrix.max() else 0
    for i in range(3):
        for j in range(3):
            color = "white" if matrix[i, j] > threshold else "black"
            ax.text(j, i, str(matrix[i, j]), ha="center", va="center", color=color)
    plotting.save_and_close(fig, out_path)


def plot_residuals(y, q_mid, out_path: pathlib.Path) -> None:
    """Histogram of the Q50 residual (realized minus median)."""
    residual = y - q_mid
    fig, ax = plotting.new_axes()
    ax.hist(residual, bins=40, color="#2171b5")
    ax.axvline(0.0, color="grey", linestyle="--", linewidth=0.8)
    ax.set_xlabel("realized minus Q50 (percent points)")
    ax.set_ylabel("count")
    ax.set_title("Q50 residual distribution")
    plotting.save_and_close(fig, out_path)


# ----------------------------------------------------------------------------------
# Reporting
# ----------------------------------------------------------------------------------
def write_markdown(result: dict, matrix: np.ndarray, out_path: pathlib.Path) -> None:
    """Write a short, human-readable metrics summary as markdown."""
    lines = [
        f"# Test results - {result['horizon']} horizon",
        "",
        f"Samples: {result['n_samples']}",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Coverage (target {result['nominal_coverage']:.2f}) | {result['coverage']:.3f} |",
        f"| Mean band width | {result['mean_band_width']:.3f} |",
        f"| Interval score | {result['interval_score']:.3f} |",
        f"| Pinball Q10 | {result['pinball_q10']:.4f} |",
        f"| Pinball Q50 | {result['pinball_q50']:.4f} |",
        f"| Pinball Q90 | {result['pinball_q90']:.4f} |",
        f"| Q50 MAE | {result['q50_mae']:.3f} |",
        f"| Q50 RMSE | {result['q50_rmse']:.3f} |",
        f"| Directional accuracy (Q50) | {result['directional_accuracy']:.3f} |",
        f"| Confusion accuracy (diagonal) | {result['confusion_accuracy']:.3f} |",
        f"| Recommendation rate (not Stay-out) | {result['recommendation_rate']:.3f} |",
        f"| Recommendation hit rate | {result['recommendation_hit_rate']:.3f} |",
        "",
        "## Directional confusion matrix",
        "",
        "Rows are predicted recommendations, columns are realized outcomes.",
        "",
        "| pred \\ actual | " + " | ".join(metrics.ACTUAL_CLASSES) + " |",
        "| --- | " + " | ".join(["---"] * 3) + " |",
    ]
    for i, row_name in enumerate(metrics.PRED_CLASSES):
        lines.append(f"| {row_name} | " + " | ".join(str(v) for v in matrix[i]) + " |")
    out_path.write_text("\n".join(lines))


def run_horizon(horizon: str) -> dict:
    """Evaluate one horizon on its held-out test split and save all outputs."""
    target = config.target_column(horizon)
    test_df = io_store.read_split(horizon, "test")
    feature_cols = modeling.get_feature_columns(test_df, target)
    X = modeling.to_model_frame(test_df, feature_cols)
    y = test_df[target].to_numpy()

    # Scored exactly as production serves it: boosters that speak in standardised
    # units, the row's own volatility multiplied back, and the conformal offset applied.
    boosters = load_boosters(horizon)
    calibration = load_calibration(horizon)
    edges = calibration.get("bucket_edges")
    sigma = modeling.volatility_scale(test_df, horizon)
    buckets, _ = modeling.position_buckets(test_df, horizon, edges)
    q_low, q_mid, q_high = modeling.predict_band(
        boosters, X, sigma, modeling.offsets_for_rows(buckets, calibration["offsets"]))

    # The rule that decides Long versus Short is fitted on the TRAIN split's own output.
    # Fitting it on the test set would be tuning the decision to the data it is about to
    # be judged on.
    train_df = io_store.read_split(horizon, "train")
    tr_buckets, _ = modeling.position_buckets(train_df, horizon, edges)
    tr_low, tr_mid, tr_high = modeling.predict_band(
        boosters, modeling.to_model_frame(train_df, feature_cols),
        modeling.volatility_scale(train_df, horizon),
        modeling.offsets_for_rows(tr_buckets, calibration["offsets"]))
    tr_p_up = metrics.probability_up(tr_low, tr_mid, tr_high)
    rule = metrics.fit_recommendation_rule(tr_p_up, tr_mid, tr_buckets,
                                           config.RECOMMENDATION_RATE[horizon],
                                           config.MIN_MOVE_PERCENTILE[horizon])

    p_up = metrics.probability_up(q_low, q_mid, q_high)
    codes = metrics.apply_recommendation_rule(p_up, q_mid, buckets, rule)

    result = metrics.evaluate_all(y, q_low, q_mid, q_high,
                                  config.NOMINAL_COVERAGE, config.QUANTILES, codes)
    result["horizon"] = horizon
    result["move_floor"] = rule["move_floor"]
    matrix = metrics.directional_confusion_matrix(y, q_low, q_high, codes)

    plot_dir = plotting.prepare_results_dir("plots", f"test_{horizon}")
    metric_dir = plotting.prepare_results_dir("metrics", f"test_{horizon}")
    report_dir = plotting.prepare_results_dir("reports", f"test_{horizon}")

    plot_interval(y, q_low, q_mid, q_high, plot_dir / "interval.png")
    plot_confusion(matrix, plot_dir / "confusion_matrix.png")
    plot_residuals(y, q_mid, plot_dir / "q50_residuals.png")

    with open(metric_dir / "metrics.json", "w") as fh:
        json.dump({**result, "confusion_matrix": matrix.tolist()}, fh, indent=2)
    write_markdown(result, matrix, report_dir / "report.md")

    # Coverage and width breakdowns: per ticker, per year, and per days-to-close
    # bin. Global coverage can hide a ticker at 65% behind another at 95%, and
    # the band must genuinely tighten as the candle close approaches.
    slices = {
        "ticker": test_df["ticker"].astype(str).to_numpy(),
        "year": pd.to_datetime(test_df["Date"]).dt.year.to_numpy(),
    }
    dtc_col = f"days_to_close_{horizon}"
    if dtc_col in test_df.columns:
        slices["days_to_close"] = np.round(test_df[dtc_col].to_numpy().astype(float), 1)

    breakdown_rows = []
    for slice_type, by in slices.items():
        for row in metrics.coverage_breakdown(y, q_low, q_high, by):
            breakdown_rows.append({"slice_type": slice_type, **row})
    pd.DataFrame(breakdown_rows).to_csv(metric_dir / "coverage_breakdown.csv", index=False)
    # Hit rate across every candidate recommendation rate. The rate is a decision, not
    # a finding, so this is the table that turns it into an informed one.
    sweep = metrics.recommendation_sweep(y, p_up, q_mid, buckets,
                                         tr_p_up, tr_mid, tr_buckets)
    pd.DataFrame(sweep).to_csv(metric_dir / "recommendation_sweep.csv", index=False)

    # Per-quantile pinball, in each quantile's own metrics subfolder.
    for qname in config.QUANTILES:
        q_dir = plotting.prepare_results_dir("metrics", f"test_{horizon}", qname)
        (q_dir / "pinball.txt").write_text(f"{result['pinball_' + qname]:.6f}\n")

    log(f"[test] {horizon}: coverage={result['coverage']:.3f} "
          f"width={result['mean_band_width']:.3f} "
          f"interval_score={result['interval_score']:.3f} "
          f"dir_acc={result['directional_accuracy']:.3f} "
          f"reco_rate={result['recommendation_rate']:.3f} "
          f"reco_hit={result['recommendation_hit_rate']:.3f}")
    return result


if __name__ == "__main__":
    for _h in config.HORIZONS:
        run_horizon(_h)