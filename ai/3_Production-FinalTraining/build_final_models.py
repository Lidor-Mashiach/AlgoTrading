"""
Build the final production models (stage 3).

For each horizon this unifies the train and test splits into the full dataset and refits
the three quantile boosters on all of it, so the shipped models use every available row.
The boosters and a metadata file are written to Inference_models/, one subfolder per
horizon, which is what the predictor and the backend load at inference time.

This is a full retrain. There is no continued training: when new data arrives, this stage
runs again from scratch. The metadata records last_trained_through per horizon.
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

import datetime as dt
import json

import numpy as np
import pandas as pd

import config
from utils import io_store, modeling
from Evaluation import metrics

from utils.log import log

HORIZONS = config.HORIZONS


def rounds_for(horizon: str, qname: str) -> int:
    """Reuse the boosting-round count chosen during development cross-validation if
    available, otherwise fall back to the configured maximum."""
    cv_path = config.RESULTS_ROOT / "metrics" / f"train_{horizon}" / qname / "cv_summary.json"
    if cv_path.exists():
        try:
            return int(round(json.loads(cv_path.read_text())["rounds_used"] / (1.0 - config.TEST_SIZE)))
        except Exception:
            pass
    return int(modeling.HORIZON_PARAMS[horizon]["n_estimators"])


def build_horizon(horizon: str) -> None:
    """Refit and persist the three quantile boosters for one horizon on all data."""
    target = config.target_column(horizon)
    train_df = io_store.read_split(horizon, "train")
    test_df = io_store.read_split(horizon, "test")
    full = pd.concat([train_df, test_df], ignore_index=True)

    feature_cols = modeling.get_feature_columns(full, target)
    last_through = str(pd.to_datetime(full["Date"]).max().date()) if "Date" in full else None
    full = full.sort_values("Date").reset_index(drop=True)

    # --- conformal calibration -------------------------------------------------
    # Hold back the most recent candles, fit on the rest, and measure how far the
    # band actually misses on data it never saw. That measurement is the offset; it
    # is what turns a band that merely looks right in-sample into one that covers.
    rounds = {q: rounds_for(horizon, q) for q in config.QUANTILES}
    calibration = modeling.fit_conformal_offset(full, horizon, feature_cols, target, rounds)
    edges = calibration["bucket_edges"]

    # --- production fit, on everything ----------------------------------------
    full_scaled, sigma_full = modeling.with_scaled_target(full, horizon, target)
    boosters = {}
    for qname, alpha in config.QUANTILES.items():
        booster = modeling.fit_full(full_scaled, horizon, alpha, feature_cols, target,
                                    rounds[qname])
        booster.save_model(str(config.inference_model_path(horizon, qname)))
        boosters[qname] = booster

    # Band-width distribution on the training data. The predictor ranks today's
    # band width against this grid to produce a calibrated per-horizon confidence.
    X_full = modeling.to_model_frame(full_scaled, feature_cols)
    buckets, _ = modeling.position_buckets(full, horizon, edges)
    low_f, mid_f, high_f = modeling.predict_band(
        boosters, X_full, sigma_full,
        modeling.offsets_for_rows(buckets, calibration["offsets"]))
    width_grid = np.percentile(high_f - low_f, np.arange(0, 101, 5)).tolist()

    # The rule that turns a band into a direction, measured across this horizon's own
    # history: a floor on how large a move is worth naming, and one margin per position
    # bucket so the rate of calls stays steady from the open of a candle to its close.
    rule = metrics.fit_recommendation_rule(
        metrics.probability_up(low_f, mid_f, high_f), mid_f, buckets,
        config.RECOMMENDATION_RATE[horizon], config.MIN_MOVE_PERCENTILE[horizon])


    metadata = {
        "horizon": horizon,
        "feature_columns": feature_cols,
        "tickers": config.TICKERS,
        "quantiles": config.QUANTILES,
        "nominal_coverage": config.NOMINAL_COVERAGE,
        "width_grid": width_grid,
        "conformal_offsets": calibration["offsets"],
        "bucket_edges": edges,
        "calibration_size": config.CALIBRATION_SIZE,
        "calibration_rows": calibration["calibration_rows"],
        "volatility_columns": config.VOLATILITY_SCALE_COLUMNS[horizon],
        "volatility_fallback": float(np.median(sigma_full)),
        "recommendation_rule": rule,
        "recommendation_rate": config.RECOMMENDATION_RATE,
        "n_rows": int(len(full)),
        "last_trained_through": last_through,
        "built_at": dt.datetime.now().isoformat(timespec="seconds"),
    }
    config.inference_metadata_path(horizon).write_text(json.dumps(metadata, indent=2))

    log(f"[final-build] {horizon}: refit on {len(full)} rows, through {last_through}, "
          f"conformal offsets [{', '.join(f'{o:+.3f}' for o in calibration['offsets'])}] "
          f"from {calibration['calibration_rows']} held-out rows "
          f"-> Inference_models/{horizon}/")


def run(horizons: list[str] | None = None) -> None:
    """Build production models for the given horizons (default: all)."""
    for horizon in horizons or HORIZONS:
        build_horizon(horizon)
    log("[final-build] done")


if __name__ == "__main__":
    # Optional horizon names as arguments, used by backend/ai_bridge/train_service.py
    # only what a new closed candle affects: python build_final_models.py daily
    selected = [h for h in sys.argv[1:] if h in HORIZONS]
    run(selected or None)