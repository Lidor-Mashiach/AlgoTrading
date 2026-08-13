"""
Train runner.

Trains the three quantile boosters for each horizon, then evaluates each horizon on its
held-out test split. Training comes first because the test stage loads the development
boosters that training produces. Comment out any tuple in STEPS to skip it (for example,
re-run only the test stage after changing a metric).
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

from utils.runner import run_steps

HERE = pathlib.Path(__file__).resolve().parent

STEPS = [
    ("train_daily.py", "Train daily Q10, Q50, Q90"),
    ("train_weekly.py", "Train weekly Q10, Q50, Q90"),
    ("train_monthly.py", "Train monthly Q10, Q50, Q90 (heaviest regularization)"),
    ("test_daily.py", "Evaluate daily on the held-out test split"),
    ("test_weekly.py", "Evaluate weekly on the held-out test split"),
    ("test_monthly.py", "Evaluate monthly on the held-out test split"),
    ("test_baseline.py", "Naive per-ticker quantile baseline on the same test split"),
]


if __name__ == "__main__":
    run_steps(HERE, STEPS)
