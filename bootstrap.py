"""
System launcher.

Brings the system up WITHOUT blocking on training. Two phases:

    1. Sync (blocking, fast): pull the latest market data so the store holds the
       newest candle before anything else runs.
    2. Model refresh (background): call the backend training bridge
       (backend/ai_bridge/train_service.train_if_needed), which retrains only the
       horizons whose latest candle is newer than the shipped model, then returns.
       It runs in a background thread so bootstrap returns and the GUI can come up.

The GUI polls ai/utils/model_status.is_ready() (via the backend) every few seconds.
While it is False a horizon is still training; when True every model is trained
through the latest candle. Freshness is a date comparison (the model's
last_trained_through vs the newest candle), so there is no stale-flag risk: a model
left from a previous day reads as not-in-sync until it retrains. The GUI must not
offer a forecast until is_ready() is True, so an old model is never shown.

Full development pipeline stays separate: python ai/runners/run_pipeline.py.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent

from backend.utils.ConfigLoader import ConfigLoader

import backend.utils.ConsoleLogger as ConsoleLogger

logger = ConsoleLogger.ConsoleLogger(caller="bootstrap")

def main() -> None:
    from backend.utils.Banner import print_banner
    print_banner()

    # Phase 1 - Run sync_main.py to for the latest market data. This is blocking, so the store has the newest candle before anything else runs.
    logger.section("Starting Sync Process")
    # sync_main is a long-running service (initial sync + background training +
    # the 24/7 scheduler), so it must NOT be waited on. Popen launches it and
    # returns, leaving it running alongside the REST API. -u keeps its logs
    # streaming instead of sitting in a buffer.
    subprocess.Popen([sys.executable, "-u", str(ROOT / "backend" / "sync_main.py")], cwd=str(ROOT))

    # Phase 2 - Run rest_main.py to start the REST API. This is non-blocking, so the GUI can come up while the model refresh runs in the background.
    logger.section("Starting RestAPI Process")
    host, port = ConfigLoader.load_rest_settings()
    subprocess.run([sys.executable, "-m", "uvicorn", "rest_main:app", "--host", host, "--port", str(port), "--reload", "--log-level", "critical", "--no-access-log"], check=True, cwd=str(ROOT / "backend"))

if __name__ == "__main__":
    main()