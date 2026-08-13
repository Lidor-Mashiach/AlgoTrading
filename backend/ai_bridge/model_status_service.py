"""
Backend <-> AI status bridge.

Thin wrapper the backend uses to check whether the models are ready, without
importing AI internals. Mirrors forecast_service.py: loads the AI status module
by file path and re-exposes it.

The GUI (through the backend) should poll is_ready() every few seconds after
launch and only offer a forecast once it returns True - so a model left from a
previous day is never used before it retrains on the latest candle.
"""

from __future__ import annotations

import importlib.util
import pathlib

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_STATUS_PATH = _REPO_ROOT / "ai" / "utils" / "model_status.py"

_status_module = None


def _status():
    """Load the AI status module once (by file path) and cache it."""
    global _status_module
    if _status_module is None:
        spec = importlib.util.spec_from_file_location("ai_model_status", _STATUS_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _status_module = module
    return _status_module


def is_ready() -> bool:
    """True only when every horizon is trained through the latest candle."""
    return _status().is_ready()


def full_status() -> dict:
    """Per-horizon freshness plus one overall 'ready' flag, as a dict for the GUI."""
    return _status().full_status()