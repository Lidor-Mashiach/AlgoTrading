"""
Train the daily horizon.

Thin wrapper. All logic lives in train_core. This script trains the three daily quantile
boosters (Q10, Q50, Q90) on the daily train split and saves them as development models.
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

import train_core

HORIZON = "daily"

if __name__ == "__main__":
    train_core.run_horizon(HORIZON)
