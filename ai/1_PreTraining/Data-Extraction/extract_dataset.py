"""
Stage 1 - Data extraction.

Reads the raw, wide, per-ticker tables that the backend owns, pools them into one
table with a ticker column, and splits that wide table into three per-horizon raw
datasets by column-name suffix. The output is written to the intermediate data store
for the feature-engineering stage to pick up.

BOUNDARY: this file must not contain backend logic. The only backend touch point is
load_raw_ticker_table, a thin adapter that reads the backend's SQLite store. Keeping
that store fresh is the backend's job (backend/main.py), driven by the runners.

The adapter is also the one place that translates the backend's column spelling into
the AI's. The exogenous series arrive named after their yfinance symbol
('^VIX_daily_last', 'DX-Y.NYB_weekly_last'); they are renamed here to the canonical
prefixes in config.SUPPORT_SERIES_PREFIX so nothing downstream has to carry a caret
or a dot in a column name.
"""

from __future__ import annotations

# --- make the ai/ root importable regardless of where this script is launched from ---
import sys
import pathlib
import sqlite3

for _parent in pathlib.Path(__file__).resolve().parents:
    if (_parent / "config.py").exists() and (_parent / "utils").is_dir():
        if str(_parent) not in sys.path:
            sys.path.insert(0, str(_parent))
        break

import pandas as pd

import config
from utils.log import log
from utils import io_store

# ----------------------------------------------------------------------------------
# GLOBAL PARAMETERS (file specific knobs on top, shared constants come from config)
# ----------------------------------------------------------------------------------
TICKERS = config.TICKERS
HORIZONS = config.HORIZONS
SHARED_COLUMNS = config.SHARED_COLUMNS

# How each horizon's columns are recognized inside the wide row. No column name
# collides across horizons, so suffix matching is unambiguous.
HORIZON_TOKENS = {
    "daily": ("_daily", "_prev_day"),
    "weekly": ("_week", "_weekly"),
    "monthly": ("_month", "_monthly"),
}

# Raw column that holds the current daily close. Copied into the universal anchor used
# by the label and the relative features. Adjust the name if the backend differs.
DAILY_CLOSE_COLUMN = "close_daily_last"

# Backend column name -> AI column name, built once from the symbol map. The backend
# writes one '<symbol>_<horizon>_last' column per exogenous series per horizon.
SUPPORT_COLUMN_RENAMES = {
    f"{symbol}_{horizon}_last": f"{prefix}_{horizon}_last"
    for symbol, prefix in config.SUPPORT_SERIES_PREFIX.items()
    for horizon in HORIZONS
}

# Per-horizon indicator columns the AI expects the backend to provide. Checked after
# pooling so a rename or a dropped indicator on the backend side surfaces loudly
# instead of silently removing a feature from the model.
EXPECTED_INDICATOR_COLUMNS = {
    horizon: (
        [f"sma_{horizon}_{p}" for p in config.MA_PERIODS]
        + [f"ema_{horizon}_{p}" for p in config.MA_PERIODS]
        + [f"bb_base_{horizon}", f"bb_upper_{horizon}", f"bb_lower_{horizon}"]
        + [f"rsi_{horizon}", f"rsi_ma_{horizon}", f"rsi_gap_{horizon}"]
        + [f"macd_{horizon}", f"macd_signal_{horizon}", f"atr_{horizon}"]
        + [f"stoch_k_{horizon}", f"stoch_d_{horizon}"]
        + [f"{prefix}_{horizon}_last" for prefix in config.SUPPORT_SERIES_PREFIX.values()]
    )
    for horizon in HORIZONS
}


# ----------------------------------------------------------------------------------
# Backend boundary: data access adapter
# ----------------------------------------------------------------------------------
def load_raw_ticker_table(ticker: str) -> pd.DataFrame:
    """Read the ticker's three horizon tables from the backend SQLite store and
    join them on date into the wide frame the pipeline expects. Exogenous series
    columns are renamed from the backend's symbol spelling to the AI's canonical
    prefixes on the way in."""
    prefix = config.TICKER_TABLE_PREFIX.get(ticker)

    if prefix is not None and config.BACKEND_DB_PATH.exists():
        connection = sqlite3.connect(config.BACKEND_DB_PATH)
        try:
            frames = [
                pd.read_sql_query(f"SELECT * FROM {prefix}_{h} ORDER BY date",
                                  connection, index_col="date")
                for h in HORIZONS
            ]
        finally:
            connection.close()
        wide = pd.concat(frames, axis=1).reset_index().rename(columns={"date": "Date"})
        wide = wide.rename(columns=SUPPORT_COLUMN_RENAMES)
        wide["ticker"] = ticker
        return wide

    raise FileNotFoundError(
        f"Backend store not found for '{ticker}': expected {config.BACKEND_DB_PATH} "
        f"with tables {prefix}_daily/_weekly/_monthly. Run the backend sync first "
        f"(python bootstrap.py, or python ai/run_pipeline.py which syncs as stage 0)."
    )

# ----------------------------------------------------------------------------------
# Pooling and splitting
# ----------------------------------------------------------------------------------
def pool_tickers(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """
    Stack the per-ticker tables into one pooled table. Each row keeps its ticker, which
    is what lets a single pooled model still specialize per index. This is also where
    the well-known extractor issue is neutralized: by stacking explicitly per ticker we
    never overwrite one ticker's rows with another's.
    """
    frames = []
    for ticker, df in tables.items():
        df = df.copy()
        df["ticker"] = ticker
        frames.append(df)
    pooled = pd.concat(frames, ignore_index=True)

    # Universal anchor close, used by the label and the relative features. Kept as a
    # helper column in every horizon dataset and dropped before the model sees it.
    if DAILY_CLOSE_COLUMN in pooled.columns:
        pooled[config.ANCHOR_CLOSE] = pooled[DAILY_CLOSE_COLUMN]
    else:
        log(f"[extract] '{DAILY_CLOSE_COLUMN}' missing, "
            f"'{config.ANCHOR_CLOSE}' not set. Label building will be limited.", "WARNING")

    if "Date" in pooled.columns:
        pooled["Date"] = pd.to_datetime(pooled["Date"], errors="coerce")
        pooled = pooled.sort_values(["ticker", "Date"]).reset_index(drop=True)
    return pooled


def select_horizon_columns(pooled: pd.DataFrame, horizon: str) -> pd.DataFrame:
    """
    Build one horizon's raw dataset by selecting columns whose name carries that
    horizon's token, plus the shared columns. Shared columns are added explicitly so
    they are never duplicated by token matching.
    """
    tokens = HORIZON_TOKENS[horizon]
    shared_present = [c for c in SHARED_COLUMNS if c in pooled.columns]
    horizon_cols = [
        c for c in pooled.columns
        if c not in SHARED_COLUMNS and any(tok in c for tok in tokens)
    ]
    context_cols = [
        c for c in config.CONTEXT_COLUMNS[horizon]
        if c in pooled.columns and c not in horizon_cols
    ]
    selected = shared_present + horizon_cols + context_cols
    return pooled[selected].copy()


def validate_pooled(pooled: pd.DataFrame) -> None:
    """Loud checks that catch silent AI-backend drift. Warnings only, so the
    pipeline still runs on partial data - but nothing goes missing quietly."""
    for horizon in HORIZONS:
        missing = [c for c in EXPECTED_INDICATOR_COLUMNS[horizon] if c not in pooled.columns]
        if missing:
            log(f"[extract] {horizon} is missing expected columns {missing}. "
                f"Check that the backend periods match config.MA_PERIODS and that its "
                f"indicator set still covers config.SUPPORT_SERIES_PREFIX.", "WARNING")
    if "Date" in pooled.columns:
        earliest = pooled["Date"].min()
        wanted = pd.Timestamp(config.HISTORY_START["monthly"])
        if pd.notna(earliest) and earliest > wanted:
            log(f"[extract] earliest raw date is {earliest.date()} but HISTORY_START "
                f"asks for {wanted.date()}. Backend fetch is too shallow.", "WARNING")


def run() -> None:
    """Pull every ticker, pool, split by horizon, and persist the raw datasets."""
    log(f"[extract] loading {len(TICKERS)} ticker tables")
    tables = {ticker: load_raw_ticker_table(ticker) for ticker in TICKERS}

    pooled = pool_tickers(tables)
    log(f"[extract] pooled table: {pooled.shape[0]} rows, {pooled.shape[1]} columns")
    validate_pooled(pooled)

    for horizon in HORIZONS:
        horizon_df = select_horizon_columns(pooled, horizon)
        start = pd.Timestamp(config.HISTORY_START[horizon])
        horizon_df = horizon_df[horizon_df["Date"] >= start].reset_index(drop=True)
        out = io_store.write_raw(horizon_df, horizon)

        log(f"[extract] {horizon}: {horizon_df.shape[1]} columns -> {out}")

    log("[extract] done")


if __name__ == "__main__":
    run()