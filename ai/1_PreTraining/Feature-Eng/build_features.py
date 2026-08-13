"""
Stage 3 - Feature engineering.

Builds the engineered training table per horizon: runs the shared feature
builders (utils/features.py), attaches the forward-looking label, keeps only
the model columns, and drops rows without a realized label. Feature NaNs (the
warm-up of long moving averages) are KEPT - LightGBM routes missing values
natively, which is exactly why LightGBM was chosen.

Looking forward is allowed for the label only and never touches a feature.
Conventions follow README.md and FEATURES.md exactly.
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

import numpy as np
import pandas as pd

import config
from utils import features, io_store, plotting

from utils.log import log
# ----------------------------------------------------------------------------------
# GLOBAL PARAMETERS
# ----------------------------------------------------------------------------------
HORIZONS = config.HORIZONS
ANCHOR = config.ANCHOR_CLOSE


# ----------------------------------------------------------------------------------
# Label building (the only place allowed to look forward)
# ----------------------------------------------------------------------------------
def build_label(df: pd.DataFrame, horizon: str) -> pd.DataFrame:
    """
    Attach target_<horizon> in percent points. For daily it is the next day's move.
    For weekly and monthly it is the move from the row's anchor to the candle's
    closing anchor. A candle's closing row is ROLLED OVER: its in-candle move is 0
    by construction, so it is relabeled with the NEXT candle's close instead -
    exactly how the daily horizon always works. Rows of the final (still open)
    candle are dropped, because their label is not realized. label_period records
    the candle each label realizes in, for leak-free grouping downstream.
    """
    target = config.target_column(horizon)
    if ANCHOR not in df.columns:
        log(f"[features] {horizon}: no anchor close, cannot build {target}")
        df[target] = np.nan
        return df

    df = df.sort_values(["ticker", "Date"]).reset_index(drop=True)

    if horizon == "daily":
        next_anchor = df.groupby("ticker")[ANCHOR].shift(-1)
        df[target] = (next_anchor / df[ANCHOR] - 1.0) * 100.0
        df[config.LABEL_PERIOD_COLUMN] = features.period_id(df["Date"], horizon)
    else:
        df["_period"] = features.period_id(df["Date"], horizon)
        # Drop the final (still open) candle per ticker: its close is not realized yet.
        last_period = df.groupby("ticker")["_period"].transform("max")
        df = df[df["_period"] < last_period].copy()

        period_close = df.groupby(["ticker", "_period"])[ANCHOR].transform("last")
        df[target] = (period_close / df[ANCHOR] - 1.0) * 100.0

        # Roll each candle's closing row over to the NEXT candle. On that row the
        # in-candle target is 0 by construction (anchor == candle close), but the
        # honest question at that moment is already "where will the NEXT candle
        # close". So the row is relabeled with the next candle's close, its
        # days_to_close becomes 1.0 (the whole next candle is still ahead), and it
        # is grouped with the next candle so no split can leak through its label.
        is_last = df.groupby(["ticker", "_period"]).cumcount(ascending=False) == 0
        closes = df.loc[is_last, ["ticker", "_period", ANCHOR]].copy()
        closes["_next_close"] = closes.groupby("ticker")[ANCHOR].shift(-1)
        closes["_next_period"] = closes.groupby("ticker")["_period"].shift(-1)

        df.loc[is_last, target] = (closes["_next_close"] / closes[ANCHOR] - 1.0) * 100.0
        df.loc[is_last, "_period"] = closes["_next_period"]

        dtc = f"days_to_close_{horizon}"
        if dtc in df.columns:
            df.loc[is_last, dtc] = 1.0

        df = df.rename(columns={"_period": config.LABEL_PERIOD_COLUMN})

    df = df.dropna(subset=[target]).reset_index(drop=True)
    df[config.LABEL_PERIOD_COLUMN] = df[config.LABEL_PERIOD_COLUMN].astype("int64")
    return df


# ----------------------------------------------------------------------------------
# Per-horizon orchestration
# ----------------------------------------------------------------------------------
def engineer_horizon(df: pd.DataFrame, horizon: str) -> tuple[pd.DataFrame, list[str]]:
    """Engineer all features for one horizon and return the table plus the model columns."""
    built = features.add_all_features(df, horizon)
    df = build_label(df, horizon)

    # Model feature set: engineered features plus the raw passthrough columns present.
    spec = features.HORIZON_SPEC[horizon]
    passthrough = [c for c in spec["passthrough"] if c in df.columns]
    model_features = built + passthrough

    # Final table: shared keys + ticker (categorical feature) + model features + label.
    target = config.target_column(horizon)
    keep = ["Date", "ticker", config.LABEL_PERIOD_COLUMN] + model_features + [target]
    keep = [c for c in dict.fromkeys(keep) if c in df.columns]  # de-dupe, preserve order
    out = df[keep].copy()

    # Keep feature NaNs (LightGBM routes them natively); drop label-less rows only.
    out = out.dropna(subset=[target]).reset_index(drop=True)
    return out, model_features


def run() -> None:
    """Engineer features and the label for every horizon and persist the results."""
    report_dir = plotting.prepare_results_dir("tables", "feature_engineering")

    for horizon in HORIZONS:
        raw = io_store.read_raw(horizon)
        engineered, model_features = engineer_horizon(raw, horizon)

        io_store.write_features(engineered, horizon)
        pd.Series(model_features, name="model_feature").to_csv(
            report_dir / f"{horizon}_features.csv", index=False
        )
        log(f"[features] {horizon}: {len(model_features)} model features, "
              f"{len(engineered)} rows -> stored")

    log("[features] done")


if __name__ == "__main__":
    run()