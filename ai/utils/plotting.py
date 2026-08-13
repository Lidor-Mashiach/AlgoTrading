"""
Plotting helpers.

Matplotlib is forced into a non-interactive (Agg) backend so nothing ever pops up a
window. Every stage writes its figures into its own results subfolder, and that folder
is cleared at the start of each run so only the latest run is kept.
"""

from __future__ import annotations

import pathlib
import shutil

import matplotlib

matplotlib.use("Agg")  # must be set before importing pyplot, disables pop-up windows
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LinearSegmentedColormap

import config

# White -> deep blue colormap for correlation magnitude (the blue-white heatmap).
BLUE_WHITE = LinearSegmentedColormap.from_list("blue_white", ["#ffffff", "#08306b"])

# Allowed top-level result categories. Outputs are grouped by what they are.
RESULT_CATEGORIES = ("plots", "reports", "metrics", "tables")


def prepare_results_dir(category: str, *parts: str) -> pathlib.Path:
    """
    Resolve and reset a results subfolder under results/<category>/, for example
    prepare_results_dir("plots", "train_daily", "q10"). The leaf folder is wiped and
    recreated so only the latest run's outputs remain. Category must be one of
    plots, reports, metrics, or tables.
    """
    if category not in RESULT_CATEGORIES:
        raise ValueError(f"Unknown results category '{category}'. "
                         f"Expected one of {RESULT_CATEGORIES}.")
    path = config.RESULTS_ROOT.joinpath(category, *parts)
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_correlation_heatmap(corr: "np.ndarray", labels: list[str], out_path: pathlib.Path,
                             title: str = "Absolute feature correlation") -> None:
    """
    Save a blue-white heatmap of absolute correlations. White means unrelated, deep
    blue means strongly correlated. Signed values are saved separately as a table, so
    this view is purely about spotting redundancy between features.
    """
    magnitude = np.abs(corr)
    n = len(labels)
    fig_side = max(6.0, 0.35 * n)
    fig, ax = plt.subplots(figsize=(fig_side, fig_side))
    im = ax.imshow(magnitude, cmap=BLUE_WHITE, vmin=0.0, vmax=1.0, aspect="auto")
    ax.set_xticks(range(n))
    ax.set_yticks(range(n))
    ax.set_xticklabels(labels, rotation=90, fontsize=6)
    ax.set_yticklabels(labels, fontsize=6)
    ax.set_title(title)
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04, label="|correlation|")
    fig.tight_layout()
    fig.savefig(out_path, dpi=config.PLOT_DPI)
    plt.close(fig)


def save_bar(values: list[float], labels: list[str], out_path: pathlib.Path,
             title: str, xlabel: str) -> None:
    """Save a simple horizontal bar chart (used for non-linear association scores)."""
    fig, ax = plt.subplots(figsize=(8.0, max(3.0, 0.3 * len(labels))))
    y = np.arange(len(labels))
    ax.barh(y, values, color="#2171b5")
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=7)
    ax.invert_yaxis()
    ax.set_xlabel(xlabel)
    ax.set_title(title)
    fig.tight_layout()
    fig.savefig(out_path, dpi=config.PLOT_DPI)
    plt.close(fig)


def new_axes(width: float = 8.0, height: float = 5.0):
    """Return a fresh (fig, ax) pair. Caller is responsible for saving and closing."""
    return plt.subplots(figsize=(width, height))


def save_and_close(fig, out_path: pathlib.Path) -> None:
    """Save a figure at the configured DPI and close it to free memory."""
    fig.tight_layout()
    fig.savefig(out_path, dpi=config.PLOT_DPI)
    plt.close(fig)
