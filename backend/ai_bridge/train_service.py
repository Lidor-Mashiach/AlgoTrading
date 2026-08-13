"""
Backend <-> AI training bridge.

The backend calls train_if_needed() right AFTER it finishes syncing market data.
It refreshes the AI feature stores from the backend's SQLite store, then retrains
ONLY the horizons whose latest closed candle is newer than the shipped model
(a daily candle triggers the daily boosters, a closed week the weekly ones, a
closed month the monthly ones). The three production boosters of a triggered
horizon are rebuilt from scratch on the full history.

This is not a script with a main - it is a function the backend imports and calls.
It runs the AI stage scripts as subprocesses (they live under ai/ and are not
importable packages), which keeps the AI/backend boundary intact. A file lock
prevents two retrains from overlapping if the backend calls twice.

No development artifacts here (no EDA, no dev models, no test reports) - the full
evaluation flow is ai/runners/run_pipeline.py and runs during development.

If no inference models exist yet, train_if_needed() returns without training and
reports that the full pipeline must be run once first.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import subprocess
import sys

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_AI_ROOT = _REPO_ROOT / "ai"
_PYTHON = sys.executable

# AI stage scripts, run in order to refresh the feature stores before training.
# EDA is skipped on purpose (a development artifact).
_PREP_STEPS = [
    "1_PreTraining/Data-Extraction/extract_dataset.py",
    "1_PreTraining/Feature-Eng/check_missing.py",
    "1_PreTraining/Feature-Eng/build_features.py",
    "1_PreTraining/Feature-Eng/split_dataset.py",
]

_LOCK_PATH = _AI_ROOT / "runners" / ".routine.lock"


def _run_ai_script(relative: str, *args: str) -> None:
    """Run one AI stage script as a subprocess, from the ai/ root, stopping on failure."""
    subprocess.run([_PYTHON, str(_AI_ROOT / relative), *args], check=True, cwd=str(_AI_ROOT))


def _ai_module(relative: str, name: str):
    """Load an AI module by file path (the AI folders are not importable packages)."""
    spec = importlib.util.spec_from_file_location(name, _AI_ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    # ai/ must be importable so the loaded module's own 'import config' / 'from utils'
    # resolve. Add it once before executing.
    if str(_AI_ROOT) not in sys.path:
        sys.path.insert(0, str(_AI_ROOT))
    spec.loader.exec_module(module)
    return module

def _all_horizons() -> list[str]:
    """The configured horizon names, for reporting after a full bootstrap."""
    return _ai_module("config.py", "ai_config").HORIZONS


def _horizons_needing_retrain() -> list[str] | None:
    """Horizons whose latest labeled candle is newer than the shipped model's
    last_trained_through. Returns None if any horizon has no model yet (caller
    should run the full pipeline first)."""
    config = _ai_module("config.py", "ai_config")
    io_store = _ai_module("utils/io_store.py", "ai_io_store")
    import pandas as pd

    needs = []
    for horizon in config.HORIZONS:
        meta_path = config.inference_metadata_path(horizon)
        if not meta_path.exists():
            return None
        trained_through = json.loads(meta_path.read_text())["last_trained_through"]
        latest = pd.to_datetime(io_store.read_features(horizon)["Date"]).max()
        if trained_through is None or latest > pd.Timestamp(trained_through):
            needs.append(horizon)
    return needs


# A lock older than this is treated as stale (its process died before cleanup),
# so a crashed run can never wedge the system forever. A full build takes about a
# minute; 7 minutes is a 7x safety margin over that.
_LOCK_STALE_SECONDS = 7 * 60


def _lock_is_stale() -> bool:
    """True if the lock file exists but is older than _LOCK_STALE_SECONDS - i.e.
    left behind by a run that was killed before its finally-block could remove it."""
    import time
    try:
        return (time.time() - _LOCK_PATH.stat().st_mtime) > _LOCK_STALE_SECONDS
    except FileNotFoundError:
        return False


def train_if_needed() -> dict:
    """
    Refresh feature stores and retrain only the horizons a new closed candle
    requires. Call this AFTER the backend sync. Returns a small status dict:

        {"status": "trained",  "horizons": [...]}   retrained these horizons
        {"status": "fresh",    "horizons": []}       nothing new, no training
        {"status": "bootstrapped", "horizons": [...]}  first run: built all models
        {"status": "busy",     "horizons": []}       another retrain is in progress

    A file lock makes overlapping calls safe. A lock left by a killed run is
    detected as stale and cleared, so a crash never wedges the system.
    """
    if _LOCK_PATH.exists() and not _lock_is_stale():
        return {"status": "busy", "horizons": []}

    _LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    _LOCK_PATH.write_text("running")
    try:
        for step in _PREP_STEPS:
            _run_ai_script(step)

        needs = _horizons_needing_retrain()
        if needs is None:
            # No inference models exist yet (fresh machine). The routine cannot
            # retrain what was never built, so run the FULL pipeline once instead:
            # train + evaluate + build every production model from scratch. After
            # this the models exist and later launches take the fast routine path.
            _run_ai_script("runners/run_pipeline.py")
            return {"status": "bootstrapped", "horizons": list(_all_horizons())}
        if not needs:
            return {"status": "fresh", "horizons": []}

        _run_ai_script("3_Production-FinalTraining/build_final_models.py", *needs)
        _run_ai_script("3_Production-FinalTraining/verify_inference.py")
        return {"status": "trained", "horizons": needs}
    finally:
        _LOCK_PATH.unlink(missing_ok=True)