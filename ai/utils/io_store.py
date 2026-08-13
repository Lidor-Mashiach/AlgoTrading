"""
Intermediate data store.

The pipeline folders run as separate scripts, so the DataFrame that starts at data
extraction and grows through feature engineering must be persisted to disk between
stages. Every stage reads its input from here and writes its output back here, which
is how the same logical table flows from PreTraining into Train and Inference_models.

Format is parquet (fast, typed, compact). If a parquet engine is missing, we fall
back to pickle so the scaffold still runs end to end.
"""

from __future__ import annotations

import pathlib

import pandas as pd

import config


def _read(path_no_ext: pathlib.Path) -> pd.DataFrame:
    """Read a frame written by _write, trying parquet first then pickle."""
    parquet_path = path_no_ext.with_suffix(".parquet")
    pickle_path = path_no_ext.with_suffix(".pkl")
    if parquet_path.exists():
        try:
            return pd.read_parquet(parquet_path)
        except Exception:
            pass
    if pickle_path.exists():
        return pd.read_pickle(pickle_path)
    raise FileNotFoundError(
        f"No stored frame at {parquet_path} or {pickle_path}. "
        f"Did an earlier pipeline stage run?"
    )


def _write(df: pd.DataFrame, path_no_ext: pathlib.Path) -> pathlib.Path:
    """Write a frame as parquet, falling back to pickle if no parquet engine exists."""
    path_no_ext.parent.mkdir(parents=True, exist_ok=True)
    try:
        out = path_no_ext.with_suffix(".parquet")
        df.to_parquet(out, index=False)
        return out
    except Exception:
        out = path_no_ext.with_suffix(".pkl")
        df.to_pickle(out)
        return out


# ---- raw per-horizon tables (after pooling and suffix split) ----------------------
def write_raw(df: pd.DataFrame, horizon: str) -> pathlib.Path:
    """Persist the raw, pooled table for one horizon."""
    return _write(df, config.RAW_DIR / horizon)


def read_raw(horizon: str) -> pd.DataFrame:
    """Load the raw, pooled table for one horizon."""
    return _read(config.RAW_DIR / horizon)


# ---- engineered per-horizon tables (features + label) -----------------------------
def write_features(df: pd.DataFrame, horizon: str) -> pathlib.Path:
    """Persist the engineered feature table (with label) for one horizon."""
    return _write(df, config.FEATURES_DIR / horizon)


def read_features(horizon: str) -> pd.DataFrame:
    """Load the engineered feature table (with label) for one horizon."""
    return _read(config.FEATURES_DIR / horizon)


# ---- train / test splits ----------------------------------------------------------
def write_split(df: pd.DataFrame, horizon: str, part: str) -> pathlib.Path:
    """Persist a split part ('train' or 'test') for one horizon."""
    return _write(df, config.SPLITS_DIR / horizon / part)


def read_split(horizon: str, part: str) -> pd.DataFrame:
    """Load a split part ('train' or 'test') for one horizon."""
    return _read(config.SPLITS_DIR / horizon / part)
