"""
Inference smoke test.

Loads the deployable models and runs one dummy prediction per horizon to confirm the
artifacts exist, load cleanly, and return a well-formed band. This is a wiring check,
not an accuracy check.
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

import config
from utils.log import log
import predictor

REQUIRED_KEYS = {"low", "mid", "high", "stability"}

def run() -> None:
    """Run a dummy prediction per horizon and assert the contract holds."""
    ticker = config.TICKERS[0]
    for horizon in config.HORIZONS:
        # Empty feature dict on purpose: every model feature falls back to NaN, which is
        # valid input for LightGBM. This checks loading and the output shape only.
        out = predictor.predict(ticker, horizon, features={})
        assert REQUIRED_KEYS.issubset(out), f"missing keys for {horizon}: {out}"
        assert out["low"] <= out["high"], f"band inverted for {horizon}: {out}"
        assert 0.0 <= out["stability"] <= 1.0, f"bad stability for {horizon}: {out}"
        log(f"[verify] {horizon}: low={out['low']:.3f} mid={out['mid']:.3f} "
              f"high={out['high']:.3f} stability={out['stability']:.2f}")

    log("[verify] all horizons returned a valid band")


if __name__ == "__main__":
    run()
