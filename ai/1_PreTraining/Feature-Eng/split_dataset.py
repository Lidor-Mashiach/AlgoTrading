"""
Stage 5 - Train/test split.

Splits each horizon's engineered table into train and test sets with three guarantees:
  - the split is at the candle (group) level first, so the intra-candle rows of one
    candle never straddle train and test (the window follows the split, not the reverse)
  - one global date cutoff decides the holdout for every ticker at once, so no index
    ever trains on dates another index is tested on. Six correlated indices share
    market-wide shocks, which is exactly what a per-ticker holdout would leak
  - a group_id column is kept in both parts so the training folds can keep whole candles
    inside a single fold

Output is one train file and one test file per horizon in the intermediate data store.
A short size summary is written to results/.
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

import pandas as pd

import config
from utils import features, io_store, plotting
from utils.log import log
# ----------------------------------------------------------------------------------
# GLOBAL PARAMETERS
# ----------------------------------------------------------------------------------
HORIZONS = config.HORIZONS
TEST_SIZE = config.TEST_SIZE
GROUP_COLUMN = "group_id"


def candle_group(df: pd.DataFrame, horizon: str) -> pd.Series:
    """
    Candle identifier per row. Uses the label_period written by the label stage -
    the candle each row's label realizes in - so rollover rows are grouped with
    the candle they predict and no split can leak through a label. Falls back to
    the shared period_id for tables that predate the column.
    """
    if config.LABEL_PERIOD_COLUMN in df.columns:
        period = df[config.LABEL_PERIOD_COLUMN]
    else:
        period = features.period_id(df["Date"], horizon)
    return df["ticker"].astype(str) + "_" + period.astype(str)




def split_one(df: pd.DataFrame, horizon: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (train_df, test_df) for one horizon using one global, time-ordered cutoff."""
    df = df.copy()
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df[GROUP_COLUMN] = candle_group(df, horizon)

    # One global time cutoff: the most recent TEST_SIZE fraction of rows becomes
    # the test set for every ticker at once, whole candles only. This removes the
    # cross-ticker leak where one ticker trains on dates another is tested on.
    group_start = df.groupby(GROUP_COLUMN)["Date"].min()
    cutoff = df["Date"].quantile(1.0 - TEST_SIZE)
    test_groups = group_start.index[group_start > cutoff]

    test_mask = df[GROUP_COLUMN].isin(set(test_groups))
    train_df = df[~test_mask].reset_index(drop=True)
    test_df = df[test_mask].reset_index(drop=True)
    return train_df, test_df


def run() -> None:
    """Split every horizon and persist the train and test parts."""
    out_dir = plotting.prepare_results_dir("tables", "split")
    summary_rows = []

    for horizon in HORIZONS:
        df = io_store.read_features(horizon)
        train_df, test_df = split_one(df, horizon)

        io_store.write_split(train_df, horizon, "train")
        io_store.write_split(test_df, horizon, "test")

        total = len(train_df) + len(test_df)
        test_pct = round(100.0 * len(test_df) / total, 2) if total else 0.0
        summary_rows.append({
            "horizon": horizon,
            "train_rows": len(train_df),
            "test_rows": len(test_df),
            "test_pct": test_pct,
            "train_groups": train_df[GROUP_COLUMN].nunique(),
            "test_groups": test_df[GROUP_COLUMN].nunique(),
        })
        log(f"[split] {horizon}: train={len(train_df)} test={len(test_df)} "
              f"({test_pct}% test)")

    pd.DataFrame(summary_rows).to_csv(out_dir / "split_summary.csv", index=False)
    log("[split] done")


if __name__ == "__main__":
    run()