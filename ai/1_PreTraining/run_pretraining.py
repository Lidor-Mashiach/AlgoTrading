"""
PreTraining runner.

Runs the data-preparation stages in order: extraction, missing-value check, feature
engineering, the train/test split, and exploratory data analysis. Comment out any
tuple in STEPS to skip that stage on the next run (for example, skip extraction once
the raw store is already populated).

EDA runs last because it reads the train split, which the split stage produces. Looking
at a correlation on the test set and acting on it is leakage through the researcher, and
it is the one leak no grouping rule can catch.
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

# (script relative to this folder, human-readable description)
STEPS = [
    ("Data-Extraction/extract_dataset.py",
     "Pull per-ticker raw tables, pool with ticker, split by suffix into 3 horizons"),
    ("Feature-Eng/check_missing.py",
     "Report missing values and drop rows with no anchor close"),
    ("Feature-Eng/build_features.py",
     "Engineer relative features and the label, drop raw price columns"),
    ("Feature-Eng/split_dataset.py",
     "Group-aware train/test split on one global date cutoff, per horizon"),
    ("Feature-Eng/run_eda.py",
     "Correlation heatmap and non-linear association report"),
]


if __name__ == "__main__":
    run_steps(HERE, STEPS)