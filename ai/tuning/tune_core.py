"""
Optuna tuning core.

One study per horizon: the three quantile boosters of a horizon share their
hyperparameters (only the pinball alpha differs), so a single search tunes the
whole band - three studies total, not nine. The objective is the mean
out-of-fold pinball loss across the three alphas, evaluated on the same
time-ordered expanding folds that training uses, so a parameter set can never
look good by peeking forward.

Coverage is recorded per trial but never optimized. The cheapest way to reach
80% coverage is an absurdly wide band, and an objective that rewards it would
buy the number by destroying the forecast. Pinball is a proper scoring rule and
prices width and misses together; coverage is read afterwards, from the user
attributes, to see what the winning parameters actually deliver.

Each study is stored in SQLite (ai/tuning/studies/<horizon>.db), so a stopped
or resubmitted job resumes where it left off. The winning parameters are
written to ai/tuning/best_params/<horizon>.json, and utils/modeling.py merges
that file over the hand-set baselines automatically on the next training run -
no manual copying.

Usage (via the thin wrappers): python tune_daily.py [n_trials]
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
import optuna

import config
from utils import features as feats
from utils import gpu, io_store, modeling
from utils.log import log
from Evaluation import metrics

# ----------------------------------------------------------------------------------
# GLOBAL PARAMETERS
# ----------------------------------------------------------------------------------
N_TRIALS = 500                   # default when no CLI argument is given
MAX_BOOST_ROUNDS = 3000          # ceiling only; early stopping picks the real count
N_STARTUP_TRIALS = 60            # random trials before the sampler starts modelling
LEAF_CEILING = 256               # upper bound on num_leaves, before the depth cap
STUDIES_DIR = config.AI_ROOT / "tuning" / "studies"
BEST_PARAMS_DIR = config.AI_ROOT / "tuning" / "best_params"

# Exactly the keys suggest_params draws. A stored study whose trials carry a different
# set was searched over a different space, and its scores cannot be compared with new
# ones. Kept beside the sampler so the two cannot drift; a self-check at the bottom of
# suggest_params enforces that.
# What the objective measures. Training fits the volatility-standardised label, so the
# search has to score that same label - trials from a differently-defined objective are
# not on a comparable scale and must never be averaged in with new ones.
# Built per horizon from config, so it names the volatility scale the label was
# divided by - see config.objective_id.

SEARCH_SPACE_KEYS = frozenset({
    "learning_rate", "max_depth", "num_leaves", "min_child_samples", "min_split_gain",
    "subsample", "bagging_freq", "colsample_bytree", "max_bin",
    "reg_alpha", "reg_lambda", "path_smooth", "extra_trees",
})


def suggest_params(trial: optuna.Trial) -> dict:
    """The search space, identical for every horizon (the data decides the rest).
    Wide on purpose so a long search has room to explore; the pruner and early
    stopping keep the cost of the extra room low.

    num_leaves is drawn AFTER max_depth and capped at 2**max_depth, because a
    fully grown tree of depth d cannot hold more leaves than that. Sampling the
    two independently lets a trial carry a leaf count that the depth makes
    unreachable, and the sampler then attributes the score to a knob that never
    took effect - the search wastes its budget learning nothing about it.
    """
    max_depth = trial.suggest_int("max_depth", 3, 12)
    leaf_cap = min(LEAF_CEILING, 2 ** max_depth)

    sampled = {
        "learning_rate": trial.suggest_float("learning_rate", 0.005, 0.15, log=True),
        "max_depth": max_depth,
        "num_leaves": trial.suggest_int("num_leaves", 4, leaf_cap),
        "min_child_samples": trial.suggest_int("min_child_samples", 5, 400),
        "min_split_gain": trial.suggest_float("min_split_gain", 0.0, 2.0),
        "subsample": trial.suggest_float("subsample", 0.5, 1.0),
        "bagging_freq": trial.suggest_int("bagging_freq", 0, 10),
        "colsample_bytree": trial.suggest_float("colsample_bytree", 0.4, 1.0),
        "max_bin": trial.suggest_int("max_bin", 127, 1023),
        "reg_alpha": trial.suggest_float("reg_alpha", 1e-3, 100.0, log=True),
        "reg_lambda": trial.suggest_float("reg_lambda", 1e-3, 100.0, log=True),
        "path_smooth": trial.suggest_float("path_smooth", 0.0, 50.0),
        "extra_trees": trial.suggest_categorical("extra_trees", [False, True]),
    }
    assert set(sampled) == SEARCH_SPACE_KEYS, "SEARCH_SPACE_KEYS is out of date"
    return sampled


def write_best_params(trial: optuna.trial.FrozenTrial, n_features: int,
                      out_path: pathlib.Path, horizon: str) -> None:
    """Persist one trial's parameters as the winning configuration for a horizon.

    n_features records the matrix width the search ran on. utils/modeling.py reads it
    back and warns when the live data no longer matches, so a parameter set can never
    be used silently against a feature set it was not searched against.
    """
    best = dict(trial.params)
    best["n_estimators"] = int(trial.user_attrs["mean_best_iter"])
    best["n_features"] = n_features
    best["objective"] = config.objective_id(horizon)
    out_path.write_text(json.dumps(best, indent=2))


def make_best_writer(n_features: int, out_path: pathlib.Path, horizon: str):
    """An Optuna callback that rewrites best_params the moment a new best trial lands.

    Writing only after study.optimize() returns loses everything when the job is killed,
    and a three-day cluster job is exactly the kind that gets killed. With this, the file
    on disk is always the best configuration found so far, so a run can be stopped,
    pre-empted or resubmitted at any point without losing the winner.
    """
    seen: dict[str, int] = {}

    def callback(study: optuna.Study, trial: optuna.trial.FrozenTrial) -> None:
        if trial.state != optuna.trial.TrialState.COMPLETE:
            return
        try:
            best = study.best_trial
        except ValueError:
            return
        if seen.get("number") == best.number:
            return
        seen["number"] = best.number
        write_best_params(best, n_features, out_path, horizon)

    return callback


def check_study_is_compatible(study: optuna.Study, horizon: str, n_features: int) -> None:
    """Refuse to extend a stored study that was searched under different conditions.

    Optuna resumes happily across a changed feature set or a changed search space, and
    then reports a best trial drawn from parameters that no longer mean the same thing -
    which would be written out stamped with today's feature count. Rather than let that
    pass, stop and say what to delete.
    """
    stored_objective = study.user_attrs.get("objective")
    stored_features = study.user_attrs.get("n_features")
    completed = [t for t in study.trials if t.state == optuna.trial.TrialState.COMPLETE]
    stored_keys = set(completed[-1].params) if completed else None

    reason = None
    objective = config.objective_id(horizon)
    if stored_objective is not None and stored_objective != objective:
        reason = (f"it scored '{stored_objective}' but the objective is now "
                  f"'{objective}'")
    elif stored_objective is None and completed:
        reason = "it predates the objective record, so it cannot be verified"
    elif stored_features is not None and stored_features != n_features:
        reason = (f"it was searched on {stored_features} features, the data now has "
                  f"{n_features}")
    elif stored_keys is not None and stored_keys != SEARCH_SPACE_KEYS:
        added = sorted(SEARCH_SPACE_KEYS - stored_keys)
        removed = sorted(stored_keys - SEARCH_SPACE_KEYS)
        reason = f"its search space differs (added {added}, removed {removed})"
    elif stored_features is None and completed:
        reason = "it predates the feature-count record, so it cannot be verified"

    if reason is None:
        study.set_user_attr("n_features", n_features)
        study.set_user_attr("objective", objective)
        return

    raise SystemExit(
        f"\n[tune] {horizon}: the stored study cannot be extended - {reason}.\n"
        f"       Its trials are not comparable with new ones, and its best trial would\n"
        f"       be written out as though it had been searched under today's conditions.\n"
        f"       Delete the study and start a fresh search:\n\n"
        f"           rm {STUDIES_DIR / (horizon + '.db')}\n"
    )


def make_objective(horizon: str, X_all, y_all, w_all, folds, device: str):
    """Build the Optuna objective: mean out-of-fold pinball over the three alphas.

    One trial = one shared parameter set, evaluated by training all three
    quantile boosters on every fold (n_splits x 3 fits) with early stopping.
    The running mean is reported per fold so the median pruner can stop
    hopeless trials early. Realized band coverage and mean band width are
    recorded alongside as user attributes - diagnostics, not objectives.
    """
    import lightgbm as lgb

    def objective(trial: optuna.Trial) -> float:
        sampled = suggest_params(trial)
        fold_scores: list[float] = []
        fold_coverage: list[float] = []
        fold_width: list[float] = []
        best_iters: list[int] = []

        for step, (tr_idx, va_idx) in enumerate(folds):
            alpha_scores = []
            edges = {}
            for qname, alpha in config.QUANTILES.items():
                params = modeling.build_params(horizon, alpha, device)
                params.pop("n_estimators", None)
                params.update(sampled)

                dtrain = modeling.make_dataset(X_all.iloc[tr_idx], y_all[tr_idx], w_all[tr_idx])
                dvalid = modeling.make_dataset(X_all.iloc[va_idx], y_all[va_idx], w_all[va_idx])
                booster = lgb.train(
                    params, dtrain,
                    num_boost_round=MAX_BOOST_ROUNDS,
                    valid_sets=[dvalid],
                    callbacks=[
                        lgb.early_stopping(modeling.EARLY_STOPPING_ROUNDS, verbose=False),
                        lgb.log_evaluation(0),
                    ],
                )
                pred = booster.predict(X_all.iloc[va_idx], num_iteration=booster.best_iteration)
                edges[qname] = pred
                alpha_scores.append(metrics.pinball_loss(y_all[va_idx], pred, alpha))
                best_iters.append(booster.best_iteration or MAX_BOOST_ROUNDS)

            low = np.minimum(edges["q10"], edges["q90"])
            high = np.maximum(edges["q10"], edges["q90"])
            fold_coverage.append(metrics.coverage(y_all[va_idx], low, high))
            fold_width.append(metrics.mean_band_width(low, high))

            fold_scores.append(float(np.mean(alpha_scores)))
            trial.report(float(np.mean(fold_scores)), step=step)
            if trial.should_prune():
                raise optuna.TrialPruned()

        # Remembered so the winning parameter set ships with a matching round count,
        # and so the band this configuration produces can be read without refitting.
        trial.set_user_attr("mean_best_iter", int(np.mean(best_iters)))
        trial.set_user_attr("coverage", float(np.mean(fold_coverage)))
        trial.set_user_attr("mean_band_width", float(np.mean(fold_width)))
        return float(np.mean(fold_scores))

    return objective


def check_store_matches_features(train_df, horizon: str) -> None:
    """Refuse to tune against a data store older than the feature code.

    data_store is a generated artifact and is not in version control, so pulling new
    feature code does not refresh it. Tuning reads the split straight off disk and will
    happily search against whatever columns it finds - three days of cluster time spent
    optimizing a feature set that no longer exists, with nothing to show it went wrong
    until the winner is used at home. Compare the split against what the current spec
    builds and stop if the store is behind.
    """
    spec = feats.HORIZON_SPEC[horizon]
    expected = [item["out"] for family in ("anchor_pct", "spread", "series_change")
                for item in spec.get(family, [])]
    missing = [c for c in expected if c not in train_df.columns]
    if not missing:
        return

    raise SystemExit(
        f"\n[tune] {horizon}: the stored train split is missing {len(missing)} column(s)\n"
        f"       the current feature spec builds: {missing}\n\n"
        f"       Either data_store predates the feature code - rebuild it with\n\n"
        f"           python ai/1_PreTraining/run_pretraining.py\n\n"
        f"       or the backend stopped supplying their inputs, in which case the\n"
        f"       extraction stage already warned by name.\n"
    )


def run(horizon: str, n_trials: int = N_TRIALS) -> None:
    """Tune one horizon end to end and persist the winning parameters."""
    STUDIES_DIR.mkdir(parents=True, exist_ok=True)
    BEST_PARAMS_DIR.mkdir(parents=True, exist_ok=True)

    target = config.target_column(horizon)
    train_df = io_store.read_split(horizon, "train")
    check_store_matches_features(train_df, horizon)
    feature_cols = modeling.get_feature_columns(train_df, target)
    macro_cols = [c for c in feature_cols
                 if c.startswith(("macd", "atr_pct", "stoch", "vix", "tnx", "irx",
                                  "dxy", "term_spread"))]
    log(f"[tune] {horizon}: training on {len(feature_cols)} features, "
        f"{len(macro_cols)} of them macro/volatility: {sorted(macro_cols)}")
    groups = train_df[modeling.GROUP_COLUMN]
    n_splits = min(config.N_SPLITS, groups.nunique() - 1)
    if n_splits < 2:
        log(f"[tune] {horizon}: not enough candle groups to tune, skipping")
        return

    scaled_df, _ = modeling.with_scaled_target(train_df, horizon, target)
    X_all = modeling.to_model_frame(scaled_df, feature_cols)
    y_all = scaled_df[target].to_numpy()
    w_all = modeling.make_sample_weight(train_df)
    folds = list(modeling.time_ordered_group_folds(train_df, groups, n_splits))
    device = gpu.resolve_lgbm_device()

    study = optuna.create_study(
        study_name=f"algotrade_{horizon}",
        storage=f"sqlite:///{STUDIES_DIR / (horizon + '.db')}",
        direction="minimize",
        load_if_exists=True,
        # Multivariate TPE models the parameters jointly, which matters here because
        # the ones that decide capacity move together - a learning rate is only good
        # or bad relative to the depth and the round count it runs with.
        sampler=optuna.samplers.TPESampler(
            seed=config.RANDOM_SEED,
            n_startup_trials=N_STARTUP_TRIALS,
            multivariate=True,
            group=True,
        ),
        pruner=optuna.pruners.MedianPruner(n_warmup_steps=1),
    )
    check_study_is_compatible(study, horizon, len(feature_cols))

    out_path = BEST_PARAMS_DIR / f"{horizon}.json"
    study.optimize(
        make_objective(horizon, X_all, y_all, w_all, folds, device),
        n_trials=n_trials,
        callbacks=[make_best_writer(len(feature_cols), out_path, horizon)],
    )

    try:
        best = study.best_trial
    except ValueError:
        log(f"[tune] {horizon}: no trial completed, {out_path.name} left as it was",
            "WARNING")
        return

    write_best_params(best, len(feature_cols), out_path, horizon)

    coverage = best.user_attrs.get("coverage")
    width = best.user_attrs.get("mean_band_width")
    log(f"[tune] {horizon}: best mean pinball={study.best_value:.4f} over "
          f"{len(study.trials)} trials -> {out_path}")
    if coverage is not None:
        log(f"[tune] {horizon}: that configuration covers {coverage:.3f} "
            f"(target {config.NOMINAL_COVERAGE:.2f}) with mean width {width:.3f}")