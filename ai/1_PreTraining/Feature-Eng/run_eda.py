"""
Stage 4 - Exploratory data analysis.

Produces two views per horizon to help judge which features carry signal and which
are redundant:
  - a blue-white heatmap of absolute correlations between model features, to spot
    redundancy (for example several distance-to-SMA features that move together)
  - a non-linear association report against the label, combining Spearman rank
    correlation (catches monotonic non-linear links that Pearson misses) and mutual
    information (catches arbitrary dependence)

This stage is exploratory only. It never drops features or rows and never looks at the
test set in a way that changes the model. Feature decisions stay explicit in the
feature-engineering stage.
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

import numpy as np
import pandas as pd

import config
from utils.log import log
from utils import io_store, plotting

# ----------------------------------------------------------------------------------
# GLOBAL PARAMETERS
# ----------------------------------------------------------------------------------
HORIZONS = config.HORIZONS
TOP_N_ASSOCIATION = 25     # how many features to show in the mutual-information bar chart
NON_FEATURE_COLS = ["Date", "ticker", config.LABEL_PERIOD_COLUMN]

def numeric_feature_columns(df: pd.DataFrame, target: str) -> list[str]:
    """Numeric model features only (ticker and Date are excluded from the numeric views)."""
    cols = [c for c in df.columns if c not in NON_FEATURE_COLS + [target]]
    return [c for c in cols if pd.api.types.is_numeric_dtype(df[c])]


def association_report(df: pd.DataFrame, features: list[str], target: str) -> pd.DataFrame:
    """Pearson, Spearman, and mutual information of each feature against the label."""
    from sklearn.feature_selection import mutual_info_regression

    clean = df[features + [target]].replace([np.inf, -np.inf], np.nan).dropna()
    if clean.empty:
        return pd.DataFrame(columns=["feature", "pearson", "spearman", "mutual_info"])

    pearson = clean[features].corrwith(clean[target]).rename("pearson")
    spearman = clean[features].corrwith(clean[target], method="spearman").rename("spearman")
    mi = mutual_info_regression(clean[features].values, clean[target].values,
                                random_state=config.RANDOM_SEED)
    mi = pd.Series(mi, index=features, name="mutual_info")

    report = pd.concat([pearson, spearman, mi], axis=1).reset_index()
    report = report.rename(columns={"index": "feature"})
    return report.sort_values("mutual_info", ascending=False).reset_index(drop=True)


def run() -> None:
    """Run correlation and association EDA for every horizon."""
    for horizon in HORIZONS:
        target = config.target_column(horizon)
        df = io_store.read_split(horizon, "train")
        features = numeric_feature_columns(df, target)
        plot_dir = plotting.prepare_results_dir("plots", "eda", horizon)
        table_dir = plotting.prepare_results_dir("tables", "eda", horizon)

        if len(features) < 2:
            log(f"[eda] {horizon}: not enough numeric features for EDA, skipping")
            continue

        # Correlation: signed matrix saved as a table, magnitude shown as the heatmap.
        corr = df[features].corr()
        corr.to_csv(table_dir / "correlation_signed.csv")
        plotting.save_correlation_heatmap(
            corr.values, features, plot_dir / "correlation_heatmap.png",
            title=f"Absolute feature correlation ({horizon})",
        )

        # Non-linear association against the label.
        report = association_report(df, features, target)
        report.to_csv(table_dir / "association.csv", index=False)
        top = report.head(TOP_N_ASSOCIATION)
        if not top.empty:
            plotting.save_bar(
                top["mutual_info"].tolist(), top["feature"].tolist(),
                plot_dir / "mutual_information_top.png",
                title=f"Top mutual information with target ({horizon})",
                xlabel="mutual information",
            )
        log(f"[eda] {horizon}: heatmap and association report saved ({len(features)} features)")

    log("[eda] done")


if __name__ == "__main__":
    run()
