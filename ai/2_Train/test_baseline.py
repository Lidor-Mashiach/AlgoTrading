"""
Naive baseline for the held-out test split.

The baseline band is FIXED per (horizon, ticker): the empirical 10th, 50th, and
90th percentiles of that ticker's TRAIN labels. No features and no model - just
"what this index historically does". The LightGBM models must clearly beat this
band (mainly on the interval score) for the feature engineering to be worth
anything, so this is the honesty check of the whole project.

Runs after the model test stage and prints a direct model-vs-baseline
comparison per horizon. Output: results/metrics/test_<horizon>/baseline/.
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
from utils import io_store, plotting
from utils.log import log
from Evaluation import metrics

# ----------------------------------------------------------------------------------
# GLOBAL PARAMETERS
# ----------------------------------------------------------------------------------
QUANTILE_LEVELS = [10, 50, 90]   # empirical percentiles taken from the train labels


def run_horizon(horizon: str) -> None:
    """Evaluate the fixed per-ticker quantile band on one horizon's test split."""
    target = config.target_column(horizon)
    train_df = io_store.read_split(horizon, "train")
    test_df = io_store.read_split(horizon, "test")

    # Fixed band per ticker from the TRAIN labels; a global band is the fallback
    # for any ticker missing from train (should not happen, but stay safe).
    global_band = np.percentile(train_df[target], QUANTILE_LEVELS)
    bands = {
        ticker: np.percentile(block[target], QUANTILE_LEVELS)
        for ticker, block in train_df.groupby("ticker")
    }

    stacked = np.vstack(
        test_df["ticker"].map(lambda t: bands.get(t, global_band)).to_numpy()
    )
    q_low, q_mid, q_high = stacked[:, 0], stacked[:, 1], stacked[:, 2]
    y = test_df[target].to_numpy()

    result = metrics.evaluate_all(y, q_low, q_mid, q_high,
                                  config.NOMINAL_COVERAGE, config.QUANTILES)
    result["horizon"] = horizon
    result["band_per_ticker"] = {t: [float(v) for v in b] for t, b in bands.items()}

    out_dir = plotting.prepare_results_dir("metrics", f"test_{horizon}", "baseline")
    with open(out_dir / "baseline.json", "w") as fh:
        json.dump(result, fh, indent=2)

    # Direct comparison against the model, when its test metrics already exist.
    model_path = config.RESULTS_ROOT / "metrics" / f"test_{horizon}" / "metrics.json"
    if model_path.exists():
        model = json.loads(model_path.read_text())
        winner = "model wins" if model["interval_score"] < result["interval_score"] \
            else "BASELINE wins - features add nothing yet"
        log(f"[baseline] {horizon}: interval score "
              f"baseline={result['interval_score']:.3f} "
              f"model={model['interval_score']:.3f} ({winner})")
    else:
        log(f"[baseline] {horizon}: interval_score={result['interval_score']:.3f} "
              f"coverage={result['coverage']:.3f} "
              f"width={result['mean_band_width']:.3f}")


if __name__ == "__main__":
    for _h in config.HORIZONS:
        run_horizon(_h)
