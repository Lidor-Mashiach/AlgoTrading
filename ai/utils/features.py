"""
Shared feature-engineering code.

Every feature builder lives here so one implementation serves three callers:
  - 1_PreTraining/Feature-Eng/build_features.py engineers the training tables
  - 1_PreTraining/Feature-Eng/split_dataset.py reuses period_id, so the split
    groups and the label candles always agree on candle boundaries
  - 3_Production-FinalTraining/predictor.py (predict_latest) engineers the
    features of the latest open row at inference time, where no label exists

period_id must stay identical to the backend's candle grouping
(Ticker_EOD_Extractor uses ISO year-week and year-month) - both sides use the
same definitions on purpose. Nothing in this file looks forward; the label is
built separately in build_features.py.

Conventions follow README.md and FEATURES.md. The running daily close (the
universal anchor) is the "close" in every relative feature, consistent with
the intra-candle convention.

Two rules decide how a raw column is used:
  - anything quoted in the ticker's own price units (a moving average, a
    Bollinger band, MACD, ATR) is non-stationary across decades and must be
    divided by the anchor before the model sees it
  - anything already unit-free (an oscillator bounded 0-100, a percent move) or
    exogenous to the ticker (an implied-volatility level, a Treasury yield, a
    dollar index) enters unchanged
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from pandas.tseries.offsets import MonthEnd

import config

MA_PERIODS = config.MA_PERIODS
ANCHOR = config.ANCHOR_CLOSE
REALIZED_VOL_WINDOW = config.REALIZED_VOL_WINDOW
TRADING_DAYS = config.TRADING_DAYS_PER_CANDLE

# Per-horizon column-name spec. Keeps the engineering generic while matching the
# exact raw names from FEATURES.md. 'passthrough' columns enter the model unchanged.
#
#   anchor_pct     price-unit column -> percent of the anchor close
#   spread         difference of two columns in the same unit; 'scale': 'anchor'
#                  additionally divides by the anchor and scales to percent
#   series_change  move of an exogenous series between consecutive candles,
#                  'pct' for a percent change and 'diff' for an absolute one
HORIZON_SPEC = {
    "daily": {
        "key": "daily",
        "rel_vol": {"out": "rel_vol_daily", "num": "volume_prev_day", "den": "volume_avg_daily_90"},
        "range": {"out": "range_pct_daily", "high": "high_prev_day", "low": "low_prev_day"},
        "rvol": {"out": "realized_vol_daily", "ret": "pct_change_daily_last"},
        "days_to_close": ["days_to_close_weekly", "days_to_close_monthly"],
        "cyclical": ["dow", "month"],
        "anchor_pct": [
            {"out": "macd_pct_daily", "num": "macd_daily"},
            {"out": "atr_pct_daily", "num": "atr_daily"},
            {"out": "atr_pct_weekly", "num": "atr_weekly"},
            {"out": "atr_pct_monthly", "num": "atr_monthly"},
        ],
        "spread": [
            {"out": "macd_hist_pct_daily", "a": "macd_daily", "b": "macd_signal_daily",
             "scale": "anchor"},
            {"out": "stoch_gap_daily", "a": "stoch_k_daily", "b": "stoch_d_daily"},
            {"out": "term_spread_daily", "a": "tnx_daily_last", "b": "irx_daily_last"},
        ],
        "series_change": [
            {"out": "vix_chg_daily", "col": "vix_daily_last", "mode": "pct"},
            {"out": "dxy_chg_daily", "col": "dxy_daily_last", "mode": "pct"},
            {"out": "tnx_chg_daily", "col": "tnx_daily_last", "mode": "diff"},
        ],
        "passthrough": ["pct_change_daily_last", "rsi_daily", "rsi_ma_daily",
                        "rsi_gap_daily", "stoch_k_daily", "stoch_d_daily",
                        "vix_daily_last", "tnx_daily_last", "irx_daily_last",
                        "dxy_daily_last",
                        "pct_change_week_current", "pct_change_month_current",
                        "vix_weekly_last", "vix_monthly_last"],
    },
    "weekly": {
        "key": "weekly",
        "rel_vol": {"out": "rel_vol_week_current", "num": "volume_week_current", "den": "volume_week_prev"},
        "range": {"out": "range_pct_week_prev", "high": "high_week_prev", "low": "low_week_prev"},
        "rvol": {"out": "realized_vol_weekly", "ret": "pct_change_week_prev"},
        "days_to_close": ["days_to_close_weekly", "days_to_close_monthly"],
        "cyclical": ["month"],
        "anchor_pct": [
            {"out": "macd_pct_weekly", "num": "macd_weekly"},
            {"out": "atr_pct_weekly", "num": "atr_weekly"},
            {"out": "atr_pct_monthly", "num": "atr_monthly"},
        ],
        "spread": [
            {"out": "macd_hist_pct_weekly", "a": "macd_weekly", "b": "macd_signal_weekly",
             "scale": "anchor"},
            {"out": "stoch_gap_weekly", "a": "stoch_k_weekly", "b": "stoch_d_weekly"},
            {"out": "term_spread_weekly", "a": "tnx_weekly_last", "b": "irx_weekly_last"},
        ],
        "series_change": [
            {"out": "vix_chg_weekly", "col": "vix_weekly_last", "mode": "pct"},
            {"out": "dxy_chg_weekly", "col": "dxy_weekly_last", "mode": "pct"},
            {"out": "tnx_chg_weekly", "col": "tnx_weekly_last", "mode": "diff"},
        ],
        "passthrough": ["pct_change_week_current", "pct_change_week_prev", "rsi_weekly",
                        "rsi_ma_weekly", "rsi_gap_weekly",
                        "stoch_k_weekly", "stoch_d_weekly",
                        "vix_weekly_last", "tnx_weekly_last", "irx_weekly_last",
                        "dxy_weekly_last",
                        "pct_change_month_current", "vix_monthly_last"],
    },
    "monthly": {
        "key": "monthly",
        "rel_vol": {"out": "rel_vol_month_current", "num": "volume_month_current", "den": "volume_month_prev"},
        "range": {"out": "range_pct_month_prev", "high": "high_month_prev", "low": "low_month_prev"},
        "rvol": {"out": "realized_vol_monthly", "ret": "pct_change_month_prev"},
        "days_to_close": ["days_to_close_monthly"],
        "cyclical": ["month"],
        "anchor_pct": [
            {"out": "macd_pct_monthly", "num": "macd_monthly"},
            {"out": "atr_pct_monthly", "num": "atr_monthly"},
        ],
        "spread": [
            {"out": "macd_hist_pct_monthly", "a": "macd_monthly", "b": "macd_signal_monthly",
             "scale": "anchor"},
            {"out": "stoch_gap_monthly", "a": "stoch_k_monthly", "b": "stoch_d_monthly"},
            {"out": "term_spread_monthly", "a": "tnx_monthly_last", "b": "irx_monthly_last"},
        ],
        "series_change": [
            {"out": "vix_chg_monthly", "col": "vix_monthly_last", "mode": "pct"},
            {"out": "dxy_chg_monthly", "col": "dxy_monthly_last", "mode": "pct"},
            {"out": "tnx_chg_monthly", "col": "tnx_monthly_last", "mode": "diff"},
        ],
        "passthrough": ["pct_change_month_current", "pct_change_month_prev", "rsi_monthly",
                        "rsi_ma_monthly", "rsi_gap_monthly",
                        "stoch_k_monthly", "stoch_d_monthly",
                        "vix_monthly_last", "tnx_monthly_last", "irx_monthly_last",
                        "dxy_monthly_last"],
    },
}


# ----------------------------------------------------------------------------------
# Small helpers
# ----------------------------------------------------------------------------------
def safe_div(num: pd.Series, den: pd.Series) -> pd.Series:
    """Element-wise division that returns NaN where the denominator is zero or missing."""
    den = den.replace(0, np.nan)
    return num / den


def has(df: pd.DataFrame, *cols: str) -> bool:
    """True only if every named column exists. Used to skip features on partial data."""
    return all(c in df.columns for c in cols)


def period_id(date: pd.Series, horizon: str) -> pd.Series:
    """
    Candle identifier per horizon: ISO year-week for weekly, year-month for monthly,
    every row its own candle for daily. This is the SINGLE definition of a candle
    on the AI side and it matches the backend extractor's week_id / month_id.
    """
    date = pd.to_datetime(date, errors="coerce")
    if horizon == "weekly":
        iso = date.dt.isocalendar()
        return (iso["year"].astype(int) * 100 + iso["week"].astype(int))
    if horizon == "monthly":
        return (date.dt.year * 100 + date.dt.month)
    return pd.Series(np.arange(len(date)), index=date.index)


def per_candle_transform(df: pd.DataFrame, horizon: str, source: str, fn) -> pd.Series:
    """
    Apply a rolling/shifting transform per ticker over CANDLES rather than rows.

    Weekly and monthly columns that describe a closed candle repeat their value on
    every intra-candle row, so a window run directly over rows would count the same
    candle several times. This collapses the frame to one row per (ticker, candle),
    applies fn to that per-ticker series, and maps the result back onto every row of
    its candle. For daily each row is already its own candle, so the transform runs
    directly. Returns a Series aligned to df.index.
    """
    if horizon == "daily":
        return df.groupby("ticker")[source].transform(fn)

    period = period_id(df["Date"], horizon)
    tmp = pd.DataFrame({"ticker": df["ticker"], "_p": period, "_v": df[source]})
    per_candle = tmp.drop_duplicates(["ticker", "_p"]).copy()
    per_candle["_out"] = per_candle.groupby("ticker")["_v"].transform(fn)
    mapping = per_candle.set_index(["ticker", "_p"])["_out"]
    keys = pd.MultiIndex.from_arrays([df["ticker"], period])
    return pd.Series(mapping.reindex(keys).to_numpy(), index=df.index)


# ----------------------------------------------------------------------------------
# Feature builders (each appends columns and records the engineered feature names)
# ----------------------------------------------------------------------------------
def add_distance_features(df: pd.DataFrame, key: str, built: list[str]) -> None:
    """Percent distance of the running close from each SMA and EMA."""
    for p in MA_PERIODS:
        sma = f"sma_{key}_{p}"
        ema = f"ema_{key}_{p}"
        if has(df, ANCHOR, sma):
            name = f"dist_sma_{key}_{p}"
            df[name] = safe_div(df[ANCHOR] - df[sma], df[sma])
            built.append(name)
        if has(df, ANCHOR, ema):
            name = f"dist_ema_{key}_{p}"
            df[name] = safe_div(df[ANCHOR] - df[ema], df[ema])
            built.append(name)


def add_bollinger_features(df: pd.DataFrame, key: str, built: list[str]) -> None:
    """Position inside the band (percent b) and band width as a volatility proxy."""
    base, upper, lower = f"bb_base_{key}", f"bb_upper_{key}", f"bb_lower_{key}"
    if has(df, ANCHOR, upper, lower):
        name = f"bb_pctb_{key}"
        df[name] = safe_div(df[ANCHOR] - df[lower], df[upper] - df[lower])
        built.append(name)
    if has(df, base, upper, lower):
        name = f"bb_width_{key}"
        df[name] = safe_div(df[upper] - df[lower], df[base])
        built.append(name)


def add_relative_volume(df: pd.DataFrame, spec: dict, built: list[str]) -> None:
    """Recent volume relative to a baseline volume (a participation signal)."""
    rv = spec["rel_vol"]
    if has(df, rv["num"], rv["den"]):
        df[rv["out"]] = safe_div(df[rv["num"]], df[rv["den"]])
        built.append(rv["out"])


def add_range_pct(df: pd.DataFrame, spec: dict, built: list[str]) -> None:
    """High-low range expressed as a percent of the running close."""
    rg = spec["range"]
    if has(df, rg["high"], rg["low"], ANCHOR):
        df[rg["out"]] = safe_div(df[rg["high"]] - df[rg["low"]], df[ANCHOR])
        built.append(rg["out"])


def add_anchor_pct(df: pd.DataFrame, spec: dict, built: list[str]) -> None:
    """
    Price-unit indicators expressed as a percent of the running close. MACD and ATR
    both come out of the backend in the ticker's own currency, so an ATR of 6 means
    something completely different on TA35 than on SPY, and something different again
    on the same index twenty years apart. Dividing by the anchor makes them one
    comparable, pooled feature - the same reasoning behind dist_sma and dist_ema.
    """
    for item in spec.get("anchor_pct", []):
        if has(df, item["num"], ANCHOR):
            df[item["out"]] = safe_div(df[item["num"]], df[ANCHOR]) * 100.0
            built.append(item["out"])


def add_spread(df: pd.DataFrame, spec: dict, built: list[str]) -> None:
    """
    Differences between two columns carrying the same unit. Covers the MACD histogram
    (its distance from its own signal line, in percent of price), the Stochastic %K
    minus %D gap, and the Treasury term spread (the long yield minus the short one),
    which is the standard read on where the rate regime sits.
    """
    for item in spec.get("spread", []):
        if not has(df, item["a"], item["b"]):
            continue
        difference = df[item["a"]] - df[item["b"]]
        if item.get("scale") == "anchor":
            if not has(df, ANCHOR):
                continue
            difference = safe_div(difference, df[ANCHOR]) * 100.0
        df[item["out"]] = difference
        built.append(item["out"])


def add_series_change(df: pd.DataFrame, horizon: str, spec: dict, built: list[str]) -> None:
    """
    Move of an exogenous series from one candle to the next. The levels themselves say
    which regime the market is in; the change says whether it is deteriorating, which is
    the part that widens a band. Percent change for the index-like series (implied
    volatility, the dollar index) and an absolute difference for the yields, which are
    already quoted in percentage points.
    """
    for item in spec.get("series_change", []):
        source = item["col"]
        if not has(df, source, "ticker", "Date"):
            continue
        if item["mode"] == "pct":
            df[item["out"]] = per_candle_transform(
                df, horizon, source, lambda s: safe_div(s, s.shift(1)) * 100.0 - 100.0
            )
        else:
            df[item["out"]] = per_candle_transform(
                df, horizon, source, lambda s: s - s.shift(1)
            )
        built.append(item["out"])


def add_realized_vol(df: pd.DataFrame, horizon: str, spec: dict, built: list[str]) -> None:
    """Rolling std of returns per ticker, computed over CANDLES. Weekly and monthly
    return columns repeat their value on every intra-candle row, so the window must
    run on one value per candle and map back. Returns are already in percent points."""
    rv = spec["rvol"]
    if not has(df, rv["ret"], "ticker", "Date"):
        return
    window = REALIZED_VOL_WINDOW[horizon]
    min_periods = max(2, window // 2)

    df[rv["out"]] = per_candle_transform(
        df, horizon, rv["ret"],
        lambda s: s.rolling(window, min_periods=min_periods).std(),
    )
    built.append(rv["out"])


def add_cyclical(df: pd.DataFrame, spec: dict, built: list[str]) -> None:
    """Cyclical (sine and cosine) encodings of day-of-week and month-of-year."""
    if "Date" not in df.columns:
        return
    date = pd.to_datetime(df["Date"], errors="coerce")
    if "dow" in spec["cyclical"]:
        dow = date.dt.dayofweek
        df["dow_sin"] = np.sin(2 * np.pi * dow / 5.0)
        df["dow_cos"] = np.cos(2 * np.pi * dow / 5.0)
        built.extend(["dow_sin", "dow_cos"])
    if "month" in spec["cyclical"]:
        month = date.dt.month
        df["month_sin"] = np.sin(2 * np.pi * month / 12.0)
        df["month_cos"] = np.cos(2 * np.pi * month / 12.0)
        built.extend(["month_sin", "month_cos"])


def add_days_to_close(df: pd.DataFrame, spec: dict, built: list[str]) -> None:
    """Trading days remaining until each listed candle closes, as a fraction. Drives
    confidence (more days left means more uncertainty) and gives the shorter horizons
    their position inside the bigger candle. Uses a business-day approximation that
    ignores market holidays until a real trading calendar is wired in."""
    if "Date" not in df.columns:
        return
    date = pd.to_datetime(df["Date"], errors="coerce")

    for name in spec["days_to_close"]:
        if name == "days_to_close_weekly":
            remaining = (4 - date.dt.dayofweek).clip(lower=0)
            df[name] = (remaining / TRADING_DAYS["weekly"]).clip(0, 1)
        elif name == "days_to_close_monthly":
            month_end = date + MonthEnd(0)
            start = (date + pd.Timedelta(days=1)).values.astype("datetime64[D]")
            end = (month_end + pd.Timedelta(days=1)).values.astype("datetime64[D]")
            remaining = np.busday_count(start, end)
            df[name] = np.clip(remaining / TRADING_DAYS["monthly"], 0, 1)
        built.append(name)


# ----------------------------------------------------------------------------------
# One entry point that runs every builder for a horizon
# ----------------------------------------------------------------------------------
def add_all_features(df: pd.DataFrame, horizon: str) -> list[str]:
    """Run every feature builder for one horizon, in place, and return the list of
    engineered column names. Works on training tables (full history) and on the
    latest raw rows at inference time exactly the same way."""
    spec = HORIZON_SPEC[horizon]
    key = spec["key"]
    built: list[str] = []

    add_distance_features(df, key, built)
    add_bollinger_features(df, key, built)
    add_relative_volume(df, spec, built)
    add_range_pct(df, spec, built)
    add_anchor_pct(df, spec, built)
    add_spread(df, spec, built)
    add_series_change(df, horizon, spec, built)
    add_realized_vol(df, horizon, spec, built)
    add_cyclical(df, spec, built)
    add_days_to_close(df, spec, built)
    return built