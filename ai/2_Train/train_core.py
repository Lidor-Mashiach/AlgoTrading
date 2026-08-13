"""
Training core (stage 2 specifics).

Wraps the shared modeling primitives in the cross-validation, plotting, and saving that
stage 2 needs. For one quantile it runs expanding-window folds over whole candles (so no
candle leaks across folds and no fold trains on data later than its validation), refits on
the full train split, saves the development booster, and writes the learning curve and a
cross-validation summary.

Fitting happens on the volatility-standardised label, the same one the production models
use, so the boosting-round counts chosen here belong to the problem actually being solved.

Band metrics such as coverage need Q10 and Q90 together and belong to the test stage. Here
the fold metric is per-quantile pinball loss.
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

import json

import numpy as np
import pandas as pd

import config
from utils import gpu, plotting, modeling
from utils.log import log
from Evaluation import metrics

GROUP_COLUMN = modeling.GROUP_COLUMN


def cross_validate_quantile(train_df: pd.DataFrame, horizon: str, alpha: float,
                            feature_cols: list[str], target: str) -> dict:
    """
    Expanding-window cross-validation for one quantile, over whole candles. Returns the
    mean out-of-fold pinball loss, the average best iteration (used to size the final
    fit), and the learning curve of the first fold for plotting.
    """
    import lightgbm as lgb

    device = gpu.resolve_lgbm_device()
    params = modeling.build_params(horizon, alpha, device)
    n_rounds = params.pop("n_estimators")

    scaled_df, _ = modeling.with_scaled_target(train_df, horizon, target)
    X_all = modeling.to_model_frame(scaled_df, feature_cols)
    y_all = scaled_df[target].to_numpy()
    w_all = modeling.make_sample_weight(train_df)
    groups = train_df[GROUP_COLUMN] if GROUP_COLUMN in train_df.columns else pd.Series(range(len(train_df)))

    n_groups = groups.nunique()
    n_splits = min(config.N_SPLITS, n_groups - 1)
    if n_splits < 2:
        # Too few groups to cross-validate (small template data). Skip CV gracefully.
        return {"mean_pinball": float("nan"), "fold_pinball": [],
                "mean_best_iter": n_rounds, "evals_result": None, "n_splits": 0}

    fold_pinball: list[float] = []
    best_iters: list[int] = []
    first_evals = None

    for fold, (tr_idx, va_idx) in enumerate(modeling.time_ordered_group_folds(train_df, groups, n_splits)):
        dtrain = modeling.make_dataset(X_all.iloc[tr_idx], y_all[tr_idx], w_all[tr_idx])
        dvalid = modeling.make_dataset(X_all.iloc[va_idx], y_all[va_idx], w_all[va_idx])
        evals: dict = {}
        booster = lgb.train(
            params, dtrain,
            num_boost_round=n_rounds,
            valid_sets=[dvalid],
            valid_names=["valid"],
            callbacks=[
                lgb.early_stopping(modeling.EARLY_STOPPING_ROUNDS, verbose=False),
                lgb.record_evaluation(evals),
                lgb.log_evaluation(0),
            ],
        )
        pred = booster.predict(X_all.iloc[va_idx], num_iteration=booster.best_iteration)
        fold_pinball.append(metrics.pinball_loss(y_all[va_idx], pred, alpha))
        best_iters.append(booster.best_iteration or n_rounds)
        if fold == 0:
            first_evals = evals

    return {
        "mean_pinball": float(np.mean(fold_pinball)),
        "fold_pinball": [float(x) for x in fold_pinball],
        "mean_best_iter": int(np.mean(best_iters)),
        "evals_result": first_evals,
        "n_splits": n_splits,
    }


def plot_learning_curve(evals_result: dict, out_path: pathlib.Path) -> None:
    """Plot validation pinball loss versus boosting round for one fold."""
    if not evals_result or "valid" not in evals_result:
        return
    metric_name = next(iter(evals_result["valid"]))
    values = evals_result["valid"][metric_name]
    fig, ax = plotting.new_axes()
    ax.plot(range(1, len(values) + 1), values, color="#2171b5")
    ax.set_xlabel("boosting round")
    ax.set_ylabel(f"validation {metric_name}")
    ax.set_title("Learning curve (fold 1)")
    plotting.save_and_close(fig, out_path)


def train_one_quantile(train_df: pd.DataFrame, horizon: str, qname: str, alpha: float,
                       feature_cols: list[str], target: str) -> dict:
    """
    Full routine for one quantile: cross-validate, refit on all train data, save the
    development booster, and write the learning curve (plots) and a CV summary (metrics).
    Returns the summary dictionary.
    """
    plot_dir = plotting.prepare_results_dir("plots", f"train_{horizon}", qname)
    metric_dir = plotting.prepare_results_dir("metrics", f"train_{horizon}", qname)

    cv = cross_validate_quantile(train_df, horizon, alpha, feature_cols, target)
    scaled_df, _ = modeling.with_scaled_target(train_df, horizon, target)
    booster = modeling.fit_full(scaled_df, horizon, alpha, feature_cols, target,
                                cv["mean_best_iter"])

    model_path = config.dev_model_path(horizon, qname)
    booster.save_model(str(model_path))

    plot_learning_curve(cv["evals_result"], plot_dir / "learning_curve.png")

    summary = {
        "horizon": horizon,
        "quantile": qname,
        "alpha": alpha,
        "n_splits": cv["n_splits"],
        "mean_pinball": cv["mean_pinball"],
        "fold_pinball": cv["fold_pinball"],
        "rounds_used": cv["mean_best_iter"],
        "n_train_rows": int(len(train_df)),
        "model_path": str(model_path),
    }
    with open(metric_dir / "cv_summary.json", "w") as fh:
        json.dump(summary, fh, indent=2)

    log(f"[train] {horizon}/{qname}: mean pinball={cv['mean_pinball']:.4f} "
          f"rounds={cv['mean_best_iter']} -> {model_path.name}")
    return summary


def run_horizon(horizon: str) -> None:
    """
    Train all three quantile boosters for one horizon. Loads the train split, then loops
    over Q10, Q50, and Q90, sending each to the shared per-quantile routine. This is the
    single call each thin per-horizon wrapper makes.
    """
    from utils import io_store

    target = config.target_column(horizon)
    train_df = io_store.read_split(horizon, "train")
    feature_cols = modeling.get_feature_columns(train_df, target)

    log(f"[train] {horizon}: {len(train_df)} train rows, {len(feature_cols)} features")
    summaries = {}
    for qname, alpha in config.QUANTILES.items():
        summaries[qname] = train_one_quantile(train_df, horizon, qname, alpha,
                                              feature_cols, target)

    # Calibrate on held-out recent candles and store the offset beside the development
    # models, so the test stage scores the same calibrated band production will serve.
    rounds = {q: s["rounds_used"] for q, s in summaries.items()}
    calibration = modeling.fit_conformal_offset(train_df, horizon, feature_cols,
                                                target, rounds)
    out_dir = plotting.prepare_results_dir("metrics", f"train_{horizon}", "calibration")
    with open(out_dir / "calibration.json", "w") as fh:
        json.dump({"horizon": horizon, **calibration,
                   "calibration_size": config.CALIBRATION_SIZE}, fh, indent=2)
    shown = ", ".join(f"{o:+.3f}" for o in calibration["offsets"])
    log(f"[train] {horizon}: conformal offsets [{shown}] per position bucket, "
        f"from {calibration['calibration_rows']} held-out rows")