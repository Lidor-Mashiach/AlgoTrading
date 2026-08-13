"""
Evaluate the weekly horizon on its held-out test split.

Thin wrapper. All logic lives in test_core. Loads the three weekly development boosters,
predicts the band on the weekly test split, and writes coverage, band width, pinball loss,
Q50 errors, the directional confusion matrix, and the figures to results/test_weekly/.
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

import test_core

HORIZON = "weekly"

if __name__ == "__main__":
    test_core.run_horizon(HORIZON)
