"""
Backend <-> AI bridge.

The single entry point the backend uses to get a forecast. get_forecast() is the
one function to call: it checks model readiness first and only then returns a band,
so a forecast is never produced from a model that has not trained on the latest
candle yet.

The return shape is ALWAYS the same, so the GUI never has to guess which structure
it received - it only reads "status":

    still training:  {"status": "training", "message": "...", "band": None}
    ready:           {"status": "ready",    "message": None,  "band": {...}}

The band (when present) is the full package, not just a range:

    ticker, horizon, based_on_date,
    low_pct, mid_pct, high_pct,                 # band + median, percent points
    low_price, mid_price, high_price, anchor_price,   # same, as prices
    stability,                                   # 0..1, how narrow vs history
    prob_up,                                     # 0..1, P(next move > 0)
    recommendation                              # "Long" / "Short" / "Stay-out"

Everything AI-facing goes through here. Tickers are accepted in either scheme -
the AI name ("TA35") or the yfinance symbol ("TA35.TA").

Requires: inference models built (ai/runners/run_pipeline.py once) and a fresh
data store (backend/ai_bridge/train_service.py, which the backend runs on sync).
"""

from __future__ import annotations

import importlib.util
import pathlib
import sqlite3
import sys

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_PREDICTOR_PATH = _REPO_ROOT / "ai" / "3_Production-FinalTraining" / "predictor.py"
_STATUS_PATH = _REPO_ROOT / "ai" / "utils" / "model_status.py"
_DB_PATH = _REPO_ROOT / "backend" / "database.db"

# yfinance symbol -> AI canonical name (the models know only the canonical names).
_YF_TO_AI = {
    "SPY": "SPY",
    "QQQ": "QQQ",
    "TA35.TA": "TA35",
    "^TA125.TA": "TA125",
    "^GDAXI": "DAX",
    "^DJI": "DJI",
}

# AI canonical name -> backend table prefix (yfinance symbol, '.' -> '_', '^' removed).
_AI_TO_PREFIX = {
    "SPY": "SPY",
    "QQQ": "QQQ",
    "TA35": "TA35_TA",
    "TA125": "TA125_TA",
    "DAX": "GDAXI",
    "DJI": "DJI",
}

_predictor_module = None
_status_module = None


def _load(path: pathlib.Path, name: str):
    ai_dir = str(pathlib.Path(__file__).parent.parent.parent / "ai")
    if ai_dir not in sys.path:
        sys.path.insert(0, ai_dir)

    # Force Python to re-resolve "utils" from the correct location
    import sys as _sys
    _sys.modules.pop("utils", None)

    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _predictor():
    """Load and cache the AI predictor module."""
    global _predictor_module
    if _predictor_module is None:
        _predictor_module = _load(_PREDICTOR_PATH, "ai_predictor")
    return _predictor_module


def _status():
    """Load and cache the AI status module."""
    global _status_module
    if _status_module is None:
        _status_module = _load(_STATUS_PATH, "ai_model_status")
    return _status_module


def _last_close(canonical: str) -> float | None:
    """Read the most recent daily close (the anchor) from the store, or None if the
    store or row is missing (the percent band is still returned without prices)."""
    prefix = _AI_TO_PREFIX.get(canonical)
    if prefix is None or not _DB_PATH.exists():
        return None
    connection = sqlite3.connect(_DB_PATH)
    try:
        row = connection.execute(
            f"SELECT close_daily_last FROM {prefix}_daily ORDER BY date DESC LIMIT 1"
        ).fetchone()
    except Exception:
        return None
    finally:
        connection.close()
    return float(row[0]) if row and row[0] is not None else None


def _build_band(ticker: str, horizon: str) -> dict:
    """The full forecast package: percent band, price band, median, stability, call."""
    canonical = _YF_TO_AI.get(ticker, ticker)
    band = _predictor().predict_latest(canonical, horizon)
    low, mid, high = band["low"], band["mid"], band["high"]

    result = {
        "ticker": canonical,
        "horizon": horizon,
        "based_on_date": band["based_on_date"],
        "low_pct": low,
        "mid_pct": mid,
        "high_pct": high,
        "stability": band["stability"],
        "prob_up": band["prob_up"],
        "recommendation": band["recommendation"],
    }

    # Percent -> price on the last close (percent points, so /100).
    anchor = _last_close(canonical)
    result["anchor_price"] = anchor
    if anchor is not None:
        result["low_price"] = anchor * (1 + low / 100.0)
        result["mid_price"] = anchor * (1 + mid / 100.0)
        result["high_price"] = anchor * (1 + high / 100.0)
    else:
        result["low_price"] = result["mid_price"] = result["high_price"] = None

    return result


def get_forecast(ticker: str, horizon: str) -> dict:
    """
    The one function the backend calls. Guards on readiness, then returns a band.
    The shape is always the same (status / message / band), so the GUI only checks
    "status": "ready" means read "band"; "training" means show a waiting state and
    poll again. A forecast is never returned while the models are still updating.
    """
    if horizon.lower() not in ("daily", "weekly", "monthly"):
        return {"status": "error",
                "message": f"unknown horizon '{horizon}'", "band": None}

    if not _status().is_ready():
        return {"status": "training",
                "message": "Models are updating, please try again shortly",
                "band": None}

    return {"status": "ready", "message": None, "band": _build_band(ticker, horizon)}