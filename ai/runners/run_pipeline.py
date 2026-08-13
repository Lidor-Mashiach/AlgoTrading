"""
Top-level pipeline runner.

Drives the whole AI module end to end, starting from a fresh backend sync:

    0. Backend sync               pull the latest market data into the SQLite store
    1. PreTraining                extract, engineer features, run EDA, split
    2. Train                      train every horizon, then evaluate on the held-out test split
    3. Production-FinalTraining   refit on all data and save the production models

Each stage runs as its own subprocess and the pipeline stops if a stage fails. Comment
out a tuple in STEPS to run only part of the pipeline (for example, skip stage 1 once the
data store is already populated).
"""

from __future__ import annotations

import pathlib
import sys

# ai/ is one level up now; add it to the path and anchor steps there.
AI_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(AI_ROOT) not in sys.path:
    sys.path.insert(0, str(AI_ROOT))

from utils.runner import run_steps

HERE = AI_ROOT

STEPS = [
    ("1_PreTraining/run_pretraining.py",
     "Stage 1 - data extraction, feature engineering, EDA, train/test split"),
    ("2_Train/run_train.py",
     "Stage 2 - train all horizons and evaluate on the held-out test split"),
    ("3_Production-FinalTraining/run_final_training.py",
     "Stage 3 - build the production models on all data"),
]


if __name__ == "__main__":
    run_steps(HERE, STEPS)
