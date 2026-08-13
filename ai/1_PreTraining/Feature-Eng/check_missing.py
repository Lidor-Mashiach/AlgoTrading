"""
Stage 2 - Missing value check.

Reports missing values per horizon and removes only the rows that can never form a
usable example (a missing anchor close). The warm-up NaNs created by long moving
averages are expected and are deliberately KEPT: LightGBM routes missing values
natively, and imputing a 200-period average before it has 200 periods behind it would
invent data. The feature-engineering stage drops rows without a realized label and
nothing else. A per-horizon report is written to results/ so the NaN pattern can still
be inspected.
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

import pandas as pd

import config
from utils.log import log
from utils import io_store, plotting

# ----------------------------------------------------------------------------------
# GLOBAL PARAMETERS
# ----------------------------------------------------------------------------------
HORIZONS = config.HORIZONS
ANCHOR_CLOSE = config.ANCHOR_CLOSE


def missing_report(df: pd.DataFrame) -> pd.DataFrame:
    """Return a per-column table of missing-value counts and percentages, worst first."""
    counts = df.isna().sum()
    pct = (counts / max(len(df), 1) * 100.0).round(2)
    report = pd.DataFrame({"missing": counts, "missing_pct": pct})
    return report[report["missing"] > 0].sort_values("missing", ascending=False)


def run() -> None:
    """Check, report, and lightly clean each horizon's raw dataset in place."""
    out_dir = plotting.prepare_results_dir("tables", "missing_values")

    for horizon in HORIZONS:
        df = io_store.read_raw(horizon)
        before = len(df)

        report = missing_report(df)
        report.to_csv(out_dir / f"{horizon}_missing.csv")
        log(f"[missing] {horizon}: {len(report)} columns contain NaNs "
              f"(saved {horizon}_missing.csv)")

        # Drop only rows that are structurally unusable: no anchor close to build the
        # label from. Warm-up NaNs in long-window features survive into training.
        if ANCHOR_CLOSE in df.columns:
            df = df.dropna(subset=[ANCHOR_CLOSE]).reset_index(drop=True)

        removed = before - len(df)
        if removed:
            log(f"[missing] {horizon}: dropped {removed} rows with no anchor close")

        io_store.write_raw(df, horizon)

    log("[missing] done")


if __name__ == "__main__":
    run()