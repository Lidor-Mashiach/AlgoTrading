"""
Production final-training runner (stage 3).

Builds the production models on all data, then runs the smoke test. Comment out the verify
step to skip the check.
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
    ("build_final_models.py", "Refit all quantiles on all data, save to Inference_models/"),
    ("verify_inference.py", "Smoke test: load the models and run a dummy prediction"),
]


if __name__ == "__main__":
    run_steps(HERE, STEPS)
