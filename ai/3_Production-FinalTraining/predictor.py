"""
Inference predictor.

The runtime entry point the backend and CLI call. Models are loaded lazily from
Inference_models/ and cached, so the first call for a horizon pays the load cost
and later calls are fast.

Two public functions, both stable:

    predict(ticker, horizon, features) -> {"low", "mid", "high", "stability"}
        Takes an already-engineered feature dict and returns the band.

    predict_latest(ticker, horizon) -> same dict plus "based_on_date"
        Builds today's engineered features from the freshest raw store
        (data_store/raw, written by stage 1) and calls predict. This is what
        the backend should call each evening - it requires the extraction
        stage to have run first, which the nightly flow does anyway.

low and high are the band edges in percent points, mid is the median.
stability is calibrated per horizon: today's band width is ranked against the
distribution of this horizon's band widths on the training data (stored in
metadata.json by build_final_models). A band narrower than most of its own
history means a calmer market -> high stability. This is separate from the fixed
80% band level. The recommendation mapping (Long, Short, Stay-out) is applied downstream by the
backend or CLI, not here.
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
from utils import features as feats
from utils import io_store, modeling
from Evaluation import metrics

# Fallback reference width (percent points) mapped to zero confidence, used only
# when the metadata carries no width distribution (models built before calibration).
CONFIDENCE_REF_WIDTH = 10.0

# Percentile levels matching the width_grid stored by build_final_models.
WIDTH_GRID_PERCENTILES = np.arange(0, 101, 5)

_CACHE: dict[str, dict] = {}


def _load_horizon(horizon: str) -> dict:
    """Load and cache the three boosters, the feature order, and the width grid."""
    if horizon in _CACHE:
        return _CACHE[horizon]

    import lightgbm as lgb

    meta_path = config.inference_metadata_path(horizon)
    if not meta_path.exists():
        raise FileNotFoundError(
            f"No inference models for horizon '{horizon}' at {meta_path.parent}. "
            f"Run 3_Production-FinalTraining/build_final_models.py first."
        )
    metadata = json.loads(meta_path.read_text())

    boosters = {}
    for qname in config.QUANTILES:
        boosters[qname] = lgb.Booster(model_file=str(config.inference_model_path(horizon, qname)))

    entry = {
        "boosters": boosters,
        "features": metadata["feature_columns"],
        "width_grid": metadata.get("width_grid"),
        "offsets": metadata.get("conformal_offsets", [0.0]),
        "bucket_edges": metadata.get("bucket_edges"),
        "vol_columns": metadata.get("volatility_columns", []),
        "vol_fallback": float(metadata.get("volatility_fallback", 1.0)),
        "rule": metadata.get("recommendation_rule"),
        "horizon": horizon,
    }
    _CACHE[horizon] = entry
    return entry


def _stability(width: float, width_grid: list | None) -> float:
    """
    Map band width to a stability score in [0, 1], calibrated per horizon. This is
    NOT the 80% band level (that is fixed); it is how narrow today's band is versus
    this horizon's historical band widths. A narrow band (calm market) scores high,
    a wide band (turbulent market) scores low.
    """
    if width_grid:
        pct = float(np.interp(width, width_grid, WIDTH_GRID_PERCENTILES))
        return float(np.clip(1.0 - pct / 100.0, 0.0, 1.0))
    return float(np.clip(1.0 - width / CONFIDENCE_REF_WIDTH, 0.0, 1.0))


def predict(ticker: str, horizon: str, features: dict) -> dict:
    """
    Predict the band for one ticker and horizon from a feature dictionary.

    Unknown feature keys are ignored and missing model features are left as NaN,
    which LightGBM handles natively. The band edges are sorted so low never
    exceeds high.
    """
    if horizon not in config.HORIZONS:
        raise ValueError(f"Unknown horizon '{horizon}'. Expected one of {config.HORIZONS}.")

    entry = _load_horizon(horizon)
    feature_cols = entry["features"]

    row = {col: features.get(col, np.nan) for col in feature_cols}
    if "ticker" in feature_cols:
        row["ticker"] = ticker
    X = pd.DataFrame([row], columns=feature_cols)
    if "ticker" in X.columns:
        X["ticker"] = pd.Categorical(X["ticker"], categories=config.TICKERS)

    # The boosters speak in units of the row's own volatility. Recover that scale from
    # the feature row, falling back to the training median when the column is absent or
    # unusable, so a single missing value degrades the band rather than breaking it.
    sigma = entry["vol_fallback"]
    for column in entry["vol_columns"]:
        value = features.get(column)
        if value is not None and np.isfinite(value) and value > 0:
            sigma = float(value)
            break

    # Which stretch of its candle this row sits in decides both how much the band is
    # widened and how far from a coin flip it must lean to be called a direction.
    edges = entry["bucket_edges"]
    if edges:
        column = f"days_to_close_{entry['horizon']}"
        position = pd.DataFrame({column: [features.get(column, np.nan)]})
        bucket, _ = modeling.position_buckets(position, entry["horizon"], edges)
    else:
        bucket = np.zeros(1, dtype=int)
    offset = modeling.offsets_for_rows(bucket, entry["offsets"])

    low, mid, high = modeling.predict_band(entry["boosters"], X, sigma, offset)
    low, mid, high = float(low[0]), float(mid[0]), float(high[0])
    p_up = float(metrics.probability_up(np.array([low]), np.array([mid]),
                                        np.array([high]))[0])
    code = int(metrics.apply_recommendation_rule(
        np.array([p_up]), np.array([mid]), bucket, entry["rule"])[0])
    return {
        "low": low,
        "mid": mid,
        "high": high,
        "stability": _stability(high - low, entry["width_grid"]),
        "prob_up": p_up,
        "recommendation": metrics.PRED_CLASSES[code],
    }


def predict_latest(ticker: str, horizon: str) -> dict:
    """
    Build the engineered features of the LATEST available row for one ticker and
    predict its band. Reads the raw store written by stage 1 (which still holds
    the open candle's rows - the label stage never touched it), runs the shared
    feature builders on this ticker's history, and takes the most recent row.

    Returns the predict() dict plus "based_on_date": the date the features describe.
    """
    raw = io_store.read_raw(horizon)
    block = raw[raw["ticker"] == ticker].sort_values("Date").copy()
    if block.empty:
        raise ValueError(
            f"No raw rows for ticker '{ticker}' in the {horizon} store. "
            f"Run 1_PreTraining first (the nightly flow does this)."
        )

    feats.add_all_features(block, horizon)
    last = block.iloc[-1].copy()

    # Rollover at inference, mirroring training: when the latest row is its
    # candle's last trading day (days_to_close of 0), that candle is finished
    # and the forecast targets the NEXT candle - the whole candle is ahead.
    dtc = f"days_to_close_{horizon}"
    if dtc in last.index and last[dtc] == 0:
        last[dtc] = 1.0

    out = predict(ticker, horizon, last.to_dict())
    out["based_on_date"] = str(pd.to_datetime(last["Date"]).date())
    return out