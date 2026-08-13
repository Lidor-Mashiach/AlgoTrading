"""
Shared modeling code.

The pieces of training that both stage 2 (Train) and stage 3 (Production-FinalTraining)
need live here, so neither stage has to import the other. That includes the per-horizon
hyperparameters and the low-level fit helpers (feature selection, the categorical ticker,
sample weighting, and a full fit). The stage-2 specifics (cross-validation, plots, saving
development models) stay inside the Train folder.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

import config

GROUP_COLUMN = "group_id"
NON_FEATURE_COLS = ["Date", GROUP_COLUMN, config.LABEL_PERIOD_COLUMN]

# Keys a tuning study records alongside its winning parameters. They describe the run,
# not the booster, so they are stripped before anything reaches LightGBM.
TUNING_META_PREFIX = "_"

# ----------------------------------------------------------------------------------
# Hyperparameters (per horizon, shared by the three quantiles of that horizon)
# ----------------------------------------------------------------------------------
# All three quantile boosters of a horizon share these settings. Only the pinball alpha
# differs, and it is set at fit time. Monthly carries the heaviest regularization because
# it has the least data and the longest memory.
_BASE = {
    "boosting_type": "gbdt",
    "n_estimators": 600,
    "learning_rate": 0.03,
    "num_leaves": 31,
    "max_depth": -1,
    "min_child_samples": 40,
    "subsample": 0.8,
    "subsample_freq": 1,
    "colsample_bytree": 0.8,
    "reg_alpha": 0.0,
    "reg_lambda": 1.0,
    "min_split_gain": 0.0,
    # Feature binning. The volatility features (ATR, Bollinger width, realized vol)
    # carry their signal in a narrow band of values, so a coarse histogram blurs
    # exactly the part of the input the tails depend on.
    "max_bin": 255,
    # Shrinks a leaf's value toward its parent when the leaf holds few samples. The
    # quantile objective has a constant hessian, which leaves extreme-quantile leaves
    # unusually noisy; smoothing along the path damps that without flattening the tails.
    "path_smooth": 0.0,
    "extra_trees": False,
    "random_state": config.RANDOM_SEED,
    # Same data and same seed must give the same booster whether the run happens on a
    # laptop or on 32 cluster cores, otherwise a tuned parameter set does not reproduce.
    "deterministic": True,
    "force_row_wise": True,
    "verbosity": -1,
}


def _with(**overrides) -> dict:
    """Return a copy of the baseline with the given keys overridden."""
    params = dict(_BASE)
    params.update(overrides)
    return params


HORIZON_PARAMS = {
    "daily": _with(),
    "weekly": _with(
        n_estimators=500,
        learning_rate=0.025,
        num_leaves=24,
        max_depth=6,
        min_child_samples=60,
        reg_lambda=2.0,
    ),
    "monthly": _with(
        n_estimators=400,
        learning_rate=0.02,
        num_leaves=15,
        max_depth=4,
        min_child_samples=80,
        subsample=0.7,
        colsample_bytree=0.7,
        reg_alpha=0.5,
        reg_lambda=5.0,
    ),
}

# Stop boosting after this many rounds without validation improvement.
EARLY_STOPPING_ROUNDS = 50

# ----------------------------------------------------------------------------------
# Optuna-tuned overrides (written by ai/tuning/, merged over the hand-set baselines)
# ----------------------------------------------------------------------------------
TUNED_PARAMS_DIR = config.AI_ROOT / "tuning" / "best_params"

# horizon -> the feature count the study ran on, or None when the file predates the
# record. Used to flag parameters that were tuned against a different feature set.
TUNED_FEATURE_COUNT: dict[str, int | None] = {}

# horizon -> the objective the study scored, or None for files that predate the record.
TUNED_OBJECTIVE: dict[str, str | None] = {}



# Horizons already reported on in this process, so a three-quantile loop warns once.
_FEATURE_CHECK_DONE: set[str] = set()

for _horizon in HORIZON_PARAMS:
    _tuned_path = TUNED_PARAMS_DIR / f"{_horizon}.json"
    if _tuned_path.exists():
        _tuned = json.loads(_tuned_path.read_text())
        TUNED_FEATURE_COUNT[_horizon] = _tuned.pop("n_features", None)
        TUNED_OBJECTIVE[_horizon] = _tuned.pop("objective", None)
        HORIZON_PARAMS[_horizon].update(
            {k: v for k, v in _tuned.items() if not k.startswith(TUNING_META_PREFIX)}
        )
        print(f"[modeling] {_horizon}: using tuned parameters ({_tuned_path.name})")


def check_tuned_against_features(horizon: str, n_features: int) -> None:
    """
    Warn when a horizon's tuned parameters were searched against a different feature
    set. A study optimizes colsample_bytree, num_leaves and the round count for the
    width of the matrix it saw, so those values stop meaning what they meant once
    features are added or removed - the booster still trains, it is just no longer
    running on a searched configuration. Re-run ai/tuning/tune_<horizon>.py to refresh.
    """
    if horizon not in TUNED_FEATURE_COUNT or horizon in _FEATURE_CHECK_DONE:
        return
    _FEATURE_CHECK_DONE.add(horizon)
    objective = TUNED_OBJECTIVE.get(horizon)
    current = config.objective_id(horizon)
    if objective != current:
        print(f"[modeling] {horizon}: tuned parameters were searched against "
              f"'{objective or 'an unrecorded objective'}' but training now optimises "
              f"'{current}'. Re-run ai/tuning/tune_{horizon}.py.")
        return

    tuned_count = TUNED_FEATURE_COUNT[horizon]
    if tuned_count is None:
        print(f"[modeling] {horizon}: tuned parameters carry no feature count; they may "
              f"predate the current feature set ({n_features} features). "
              f"Re-run ai/tuning/tune_{horizon}.py to be sure.")
    elif tuned_count != n_features:
        print(f"[modeling] {horizon}: tuned parameters were searched on {tuned_count} "
              f"features but the data now has {n_features}. "
              f"Re-run ai/tuning/tune_{horizon}.py.")


# ----------------------------------------------------------------------------------
# Volatility scaling and conformal calibration
# ----------------------------------------------------------------------------------
def volatility_scale(df: pd.DataFrame, horizon: str) -> np.ndarray:
    """
    The volatility estimate a horizon's label is divided by before fitting.

    Index moves are heteroscedastic: a month in a crash and a month in a calm tape are
    the same shape once each is divided by its own volatility, and wildly different
    otherwise. Fitting the quantiles on the standardised move lets one model describe
    both regimes, and multiplying the scale back afterwards makes the band widen in
    turbulence by construction instead of relying on the trees to infer the magnitude.

    Every candidate column is backward-looking, so this is known at prediction time.
    Missing or zero values fall back to the ticker's own median, then the global one.
    """
    for column in config.VOLATILITY_SCALE_COLUMNS[horizon]:
        if column not in df.columns:
            continue
        scale = df[column].astype(float).replace(0.0, np.nan)
        if "ticker" in df.columns:
            scale = scale.fillna(df.groupby("ticker")[column].transform("median"))
        scale = scale.fillna(scale.median())
        if scale.notna().all() and (scale > 0).all():
            return scale.to_numpy()
    return np.ones(len(df))


def position_buckets(df: pd.DataFrame, horizon: str, edges: list | None = None):
    """
    Which stretch of its candle each row sits in, as an integer bucket, plus the edges.

    Rows of the same weekly candle are not interchangeable: one with four days left faces
    a far wider spread than one with a day left, so a correction measured across all of
    them fits neither. Bucketing on days-to-close lets each stretch carry its own. Passing
    `edges` reuses the boundaries measured at build time, which is what keeps inference
    identical to the calibration it inherited. Horizons without a position - daily always
    forecasts one whole candle ahead - collapse to a single bucket.
    """
    column = f"days_to_close_{horizon}"
    if column not in df.columns:
        return np.zeros(len(df), dtype=int), None

    values = df[column].to_numpy(dtype=float)
    if edges is None:
        usable = values[np.isfinite(values)]
        if usable.size == 0:
            return np.zeros(len(df), dtype=int), None
        edges = np.unique(np.quantile(usable,
                                      np.linspace(0.0, 1.0, config.CALIBRATION_BUCKETS + 1)))
        if len(edges) < 2:
            return np.zeros(len(df), dtype=int), None
    edges = np.asarray(edges, dtype=float)
    index = np.clip(np.searchsorted(edges, values, side="right") - 1, 0, len(edges) - 2)
    return index.astype(int), edges.tolist()


def conformal_offset(y: np.ndarray, low: np.ndarray, high: np.ndarray,
                     alpha: float) -> float:
    """
    The amount the band has to move outward to reach its nominal coverage.

    For every calibration row, how far outside the band the outcome landed (negative
    when it landed inside). Taking the (1-alpha) quantile of those distances gives the
    smallest widening that would have covered the required share of them - and since
    the calibration rows were never trained on, that widening carries a finite-sample
    coverage guarantee rather than a hope. Applied on the standardised scale, so the
    correction inherits the volatility scaling and stays proportional to conditions.
    """
    scores = np.maximum(low - y, y - high)
    n = len(scores)
    if n == 0:
        return 0.0
    level = min(1.0, np.ceil((n + 1) * (1.0 - alpha)) / n)
    return float(np.quantile(scores, level, method="higher"))


def calibration_split(df: pd.DataFrame, fraction: float | None = None):
    """Split a frame into (proper_train, calibration) by candle, in time order, so the
    calibration slice is the most recent stretch and no candle straddles the two."""
    fraction = config.CALIBRATION_SIZE if fraction is None else fraction
    groups = df[GROUP_COLUMN]
    order = df.groupby(groups)["Date"].min().sort_values().index.to_numpy()
    n_cal = max(1, int(len(order) * fraction))
    is_cal = groups.isin(set(order[-n_cal:])).to_numpy()
    return df[~is_cal], df[is_cal], is_cal


def with_scaled_target(df: pd.DataFrame, horizon: str, target: str):
    """Return (frame whose label is divided by its volatility, that volatility).
    Every stage fits on the standardised label, so training, evaluation and inference
    cannot drift apart on what the boosters were asked to predict."""
    sigma = volatility_scale(df, horizon)
    scaled = df.copy()
    scaled[target] = df[target].to_numpy() / sigma
    return scaled, sigma


def predict_band(boosters: dict, X: pd.DataFrame, sigma, offset=0.0):
    """
    Turn three boosters into a calibrated band in percent points.

    The boosters speak in standardised units, so the conformal offset is applied there
    - which is what makes the widening proportional to the row's own volatility - and
    the scale is multiplied back last. Edges are sorted, because the three quantiles
    are separate models and nothing forces them to stay in order on every row.
    """
    z = {q: np.asarray(b.predict(X)) for q, b in boosters.items()}
    low = np.minimum(z["q10"], z["q90"]) - offset
    high = np.maximum(z["q10"], z["q90"]) + offset
    return low * sigma, z["q50"] * sigma, high * sigma


def offsets_for_rows(bucket_index: np.ndarray, offsets) -> np.ndarray:
    """Map a per-bucket offset table onto rows. A scalar broadcasts unchanged."""
    table = np.atleast_1d(np.asarray(offsets, dtype=float))
    if table.size == 1:
        return np.full(len(bucket_index), float(table[0]))
    return table[np.clip(bucket_index, 0, table.size - 1)]


def fit_conformal_offset(df: pd.DataFrame, horizon: str, feature_cols: list[str],
                         target: str, rounds: dict[str, int]) -> dict:
    """
    Hold back the most recent candles, fit on the rest, and measure how far the band
    misses on them - separately for each stretch of the candle.

    Returns the offsets, the bucket edges they were measured against, and the row count,
    all of which travel together into the metadata. Shared by the train and production
    stages so both calibrate identically.
    """
    proper, calib, _ = calibration_split(df)
    proper_scaled, _ = with_scaled_target(proper, horizon, target)
    calib_scaled, _ = with_scaled_target(calib, horizon, target)
    boosters = {q: fit_full(proper_scaled, horizon, a, feature_cols, target, rounds[q])
                for q, a in config.QUANTILES.items()}
    low, _, high = predict_band(boosters, to_model_frame(calib_scaled, feature_cols),
                               sigma=1.0)
    y = calib_scaled[target].to_numpy()
    alpha = 1.0 - config.NOMINAL_COVERAGE

    index, edges = position_buckets(calib, horizon)
    n_buckets = 1 if edges is None else len(edges) - 1
    offsets = []
    for b in range(n_buckets):
        mask = index == b
        # A bucket too thin to estimate its own quantile falls back to the pooled one,
        # which is conservative rather than noisy.
        source = mask if mask.sum() >= 50 else np.ones(len(y), dtype=bool)
        offsets.append(conformal_offset(y[source], low[source], high[source], alpha))

    return {"offsets": offsets, "bucket_edges": edges, "calibration_rows": int(len(calib))}


def time_ordered_group_folds(train_df: pd.DataFrame, groups: pd.Series, n_splits: int):
    """Expanding-window folds over whole candles: order groups by start date, cut
    into n_splits + 1 contiguous blocks, validate block k on a model trained only
    on blocks 0..k-1. No fold ever trains on data later than its validation."""
    order = train_df.groupby(groups)["Date"].min().sort_values().index.to_numpy()
    blocks = np.array_split(order, n_splits + 1)
    group_values = groups.to_numpy()
    for k in range(1, n_splits + 1):
        tr_idx = np.flatnonzero(np.isin(group_values, np.concatenate(blocks[:k])))
        va_idx = np.flatnonzero(np.isin(group_values, blocks[k]))
        yield tr_idx, va_idx


# ----------------------------------------------------------------------------------
# Feature frame and weights
# ----------------------------------------------------------------------------------
def get_feature_columns(df: pd.DataFrame, target: str) -> list[str]:
    """Model feature columns: everything except Date, the label, and the group id.
    The ticker column stays, as a categorical feature."""
    return [c for c in df.columns if c not in NON_FEATURE_COLS + [target]]


def to_model_frame(df: pd.DataFrame, feature_cols: list[str]) -> pd.DataFrame:
    """Build the feature frame with ticker as a fixed-category dtype, so train, test, and
    inference all share the same category mapping."""
    X = df[feature_cols].copy()
    if "ticker" in X.columns:
        X["ticker"] = pd.Categorical(X["ticker"], categories=config.TICKERS)
    return X


def make_sample_weight(df: pd.DataFrame) -> np.ndarray:
    """Balanced per-ticker weights: under-represented indices are up-weighted so a long
    history does not dominate a short one."""
    if "ticker" not in df.columns:
        return np.ones(len(df))
    counts = df["ticker"].value_counts()
    n_tickers = len(counts)
    weights = df["ticker"].map(lambda t: len(df) / (n_tickers * counts[t]))
    return weights.to_numpy()


# ----------------------------------------------------------------------------------
# LightGBM helpers
# ----------------------------------------------------------------------------------
def build_params(horizon: str, alpha: float, device: str) -> dict:
    """Assemble the LightGBM parameter dict for one horizon and one quantile."""
    params = dict(HORIZON_PARAMS[horizon])
    params["objective"] = "quantile"
    params["alpha"] = alpha
    params["metric"] = "quantile"
    params["device"] = device
    return params


def make_dataset(X: pd.DataFrame, y: np.ndarray, w: np.ndarray):
    """Wrap a feature frame in a LightGBM Dataset with ticker as a categorical feature."""
    import lightgbm as lgb
    return lgb.Dataset(
        X, label=y, weight=w,
        categorical_feature=["ticker"] if "ticker" in X.columns else "auto",
        free_raw_data=False,
    )


def fit_full(train_df: pd.DataFrame, horizon: str, alpha: float,
             feature_cols: list[str], target: str, num_boost_round: int):
    """Fit one quantile on an entire frame for a fixed number of rounds (no early stop).
    Used by stage 2 for the development model and by stage 3 for the production model."""
    import lightgbm as lgb
    from utils import gpu

    check_tuned_against_features(horizon, len(feature_cols))
    device = gpu.resolve_lgbm_device()
    params = build_params(horizon, alpha, device)
    params.pop("n_estimators", None)

    X = to_model_frame(train_df, feature_cols)
    y = train_df[target].to_numpy()
    w = make_sample_weight(train_df)
    dtrain = make_dataset(X, y, w)
    return lgb.train(params, dtrain, num_boost_round=max(1, num_boost_round),
                     callbacks=[lgb.log_evaluation(0)])