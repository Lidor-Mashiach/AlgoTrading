"""Tune the weekly horizon. Thin wrapper - all logic lives in tune_core."""
from __future__ import annotations

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import tune_core

HORIZON = "weekly"

if __name__ == "__main__":
    n_trials = int(sys.argv[1]) if len(sys.argv) > 1 else tune_core.N_TRIALS
    tune_core.run(HORIZON, n_trials)