"""
Model freshness status - the read-only check the backend/GUI polls.

The single source of truth is a date comparison, never a stored boolean flag (a
boolean can go stale; a date cannot): a horizon is "in sync" when the model's
last_trained_through equals the latest closed candle in the data store. If they
differ, a newer candle exists that the shipped model has not trained on, so the GUI
should keep showing "updating..." until this returns in_sync.

Typical GUI loop: call is_ready() every few seconds; while False, show a waiting
state (with a cancel option). Training runs in the background (bootstrap.py); this
module only reports, it never trains. No side effects - safe to call as often as
you like. The GUI must not offer a forecast until is_ready() is True.
"""

from __future__ import annotations

import json
import pathlib
import sys

# ai/ is one level up (this file lives in ai/utils/).
AI_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(AI_ROOT) not in sys.path:
    sys.path.insert(0, str(AI_ROOT))

import pandas as pd

import config
from utils import io_store


from utils.log import log
def horizon_status(horizon: str) -> dict:
    """Freshness of one horizon: the model's trained-through date, the latest candle
    in the store, and whether they match (in_sync)."""
    meta_path = config.inference_metadata_path(horizon)
    if not meta_path.exists():
        return {"horizon": horizon, "in_sync": False, "reason": "no model yet",
                "trained_through": None, "latest_candle": None}

    trained_through = json.loads(meta_path.read_text())["last_trained_through"]
    latest = pd.to_datetime(io_store.read_features(horizon)["Date"]).max()
    latest_str = str(latest.date()) if pd.notna(latest) else None

    in_sync = (trained_through is not None
               and latest_str == str(pd.Timestamp(trained_through).date()))
    return {
        "horizon": horizon,
        "in_sync": in_sync,
        "reason": "up to date" if in_sync else "a newer candle needs training",
        "trained_through": trained_through,
        "latest_candle": latest_str,
    }


def full_status() -> dict:
    """Freshness of every horizon plus one overall flag. This is what the backend
    exposes to the GUI; poll it while bringing the system up."""
    per_horizon = [horizon_status(h) for h in config.HORIZONS]
    return {
        "ready": all(h["in_sync"] for h in per_horizon),
        "horizons": per_horizon,
    }


def is_ready() -> bool:
    """Convenience boolean: True only when every horizon is trained through the
    latest candle. The one call a simple GUI poll loop needs."""
    return full_status()["ready"]


if __name__ == "__main__":
    log(json.dumps(full_status(), indent=2))