"""
Global configuration for the Algo-Trade AI module.

This is the single source of truth for cross-cutting constants used by every stage
of the pipeline (data extraction, feature engineering, splitting, training, evaluation,
and inference). File-specific knobs still live at the top of each script, but anything
shared across files is defined here so the values never drift apart.

Nothing in this file pulls data or trains a model. It only declares constants and paths.
"""

from __future__ import annotations

import pathlib

# ----------------------------------------------------------------------------------
# Paths (all absolute, derived from this file's location so the pipeline is CWD-safe)
# ----------------------------------------------------------------------------------
AI_ROOT = pathlib.Path(__file__).resolve().parent

DATA_STORE_DIR = AI_ROOT / "data_store"      # intermediate DataFrames that flow between folders
RAW_DIR = DATA_STORE_DIR / "raw"             # per-horizon raw tables (after pooling and suffix split)
FEATURES_DIR = DATA_STORE_DIR / "features"   # per-horizon engineered tables (features + label)
SPLITS_DIR = DATA_STORE_DIR / "splits"       # per-horizon train/test parquet files

INFERENCE_MODELS_DIR = AI_ROOT / "Inference_models"  # final production boosters that ship
DEV_MODELS_DIR = AI_ROOT / "dev_models"      # stage-2 development boosters (diagnostic)
RESULTS_ROOT = AI_ROOT / "results"           # plots, reports, metrics, tables; latest run only

BACKEND_DB_PATH = AI_ROOT.parent / "backend" / "database.db"

# AI name -> backend table prefix (yfinance symbol, '.' -> '_', '^' removed)
TICKER_TABLE_PREFIX = {
    "SPY": "SPY",
    "QQQ": "QQQ",
    "TA35": "TA35_TA",
    "TA125": "TA125_TA",
    "DAX": "GDAXI",
    "DJI": "DJI",
}

# Exogenous market series the backend stores beside every ticker's own indicators.
# The backend names those columns after its yfinance symbol, so they arrive as
# '^VIX_daily_last' or 'DX-Y.NYB_weekly_last' - names carrying characters that are
# awkward to reference and that no AI-side spec should have to know about. The
# extraction adapter renames them to these canonical prefixes on the way in, which
# is the ONLY place the backend's symbol spelling is allowed to matter.
SUPPORT_SERIES_PREFIX = {
    "^VIX": "vix",            # implied volatility of S&P options - the risk gauge
    "^TNX": "tnx",            # 10-year Treasury yield
    "^IRX": "irx",            # 13-week Treasury yield
    "DX-Y.NYB": "dxy",        # US dollar index
}


# ----------------------------------------------------------------------------------
# Universe and model layout
# ----------------------------------------------------------------------------------
# Pooled indices only. Single stocks and meme stocks are intentionally excluded
# because pooling assumes homogeneous, index-like dynamics.
TICKERS = ["SPY", "QQQ", "TA35", "TA125", "DAX", "DJI"]

HORIZONS = ["daily", "weekly", "monthly"]

# Cross-horizon context: raw columns from a LONGER horizon that a shorter horizon
# is allowed to see. They encode "where are we inside the bigger candle" and "what
# regime is the wider market in", so the daily model knows the week or month may
# have already priced the move in, and knows whether it is forecasting into a calm
# tape or a turbulent one. Everything here is known at the row's close - no leakage.
CONTEXT_COLUMNS = {
    "daily": [
        "pct_change_week_current", "pct_change_month_current",
        "vix_weekly_last", "vix_monthly_last",
        "atr_weekly", "atr_monthly",
    ],
    "weekly": [
        "pct_change_month_current",
        "vix_monthly_last",
        "atr_monthly",
    ],
    "monthly": [],
}
# Quantile name -> alpha passed to the LightGBM pinball loss. This alpha is the ONLY
# thing that differs between the three boosters of a horizon. The label is a single
# real value shared by all three.
QUANTILES = {"q10": 0.10, "q50": 0.50, "q90": 0.90}

# Fraction of the training data, taken as the most RECENT candles, held back to
# calibrate the band. The models never train on it, so the conformal adjustment
# derived from it is an honest out-of-sample measurement of how far the band misses.
# Recent on purpose: a correction fitted on the newest data tracks today's regime.
CALIBRATION_SIZE = 0.15

# Volatility estimate each horizon's label is divided by before fitting, and
# multiplied back by afterwards. A crash month and a calm month are the same shape
# once divided by their own volatility, so standardising lets one model describe
# both, and the band then scales with conditions by construction rather than by
# hoping the trees learn the scale. First column present wins.
# The monthly entry leads with implied volatility rather than realised. Realised
# volatility over 12 monthly candles is a year-long look-back: it cannot react to a
# crash inside the month the crash happens, which is exactly when the band needs to
# widen. Implied volatility is the market's forward estimate and moves the same day.
# Conformal calibration only guarantees coverage while the calibration slice and the
# forecast come from the same regime, so when the scale cannot track the regime, the
# guarantee is what breaks.
VOLATILITY_SCALE_COLUMNS = {
    "daily": ["realized_vol_daily", "atr_pct_daily"],
    "weekly": ["realized_vol_weekly", "atr_pct_weekly"],
    "monthly": ["vix_monthly_last", "realized_vol_monthly", "atr_pct_monthly"],
}


def objective_id(horizon: str) -> str:
    """
    What a tuning study for this horizon is scoring, as a string.

    Training fits the label after dividing by the first available column above, so
    changing that column changes the scale of the loss and therefore what the
    hyperparameters mean. Naming the column here lets a study refuse to be extended
    across such a change instead of averaging two incomparable objectives together.
    """
    return f"pinball-scaled-by-{VOLATILITY_SCALE_COLUMNS[horizon][0]}"

# Share of rows that receive a direction rather than Stay-out. The cut is a margin
# either side of a coin flip, sized from the model's own distribution of P(move > 0)
# so that this share of it falls outside, and stored per horizon at build time.
#
# An absolute threshold cannot work here. Asking for P(up) above some fixed level is
# asking the model to be confident about direction, and on index returns the honest
# answer is that it never is - which is what collapses every call to Stay-out. What
# the model can rank is which setups lean further from a coin flip than its own
# typical one, so the share is a design choice rather than a fact about the market.
#
# The margin is symmetric about 0.5, so nothing forces Long and Short to appear in
# equal numbers. A horizon that has drifted upward for decades will produce mostly
# Longs, and that asymmetry is the finding rather than a bias to correct. Read
# Held high on purpose: MIN_MOVE_PERCENTILE below is the control that actually decides
# how often a direction is named, and letting the rate bind first would put two knobs in
# charge of one thing. Set a horizon to 0.0 to silence its recommendations entirely.
# results/metrics/test_<horizon>/recommendation_sweep.csv sweeps both knobs together.
RECOMMENDATION_RATE = {"daily": 0.90, "weekly": 0.90, "monthly": 0.90}

# Number of position-in-candle buckets the calibration and the recommendation rule are
# fitted separately within. A weekly band with four days left is roughly twice as wide as
# one with a single day left, so a single correction cannot serve both: it leaves the
# opening of the candle under-covered and its close over-covered, and it lets the rate of
# directional calls drift with position rather than with the market. Bucketing gives each
# stretch of the candle its own correction and its own margin. Ignored on the daily
# horizon, which always forecasts one whole candle ahead and has no position to speak of.
CALIBRATION_BUCKETS = 5

# A direction is only named when the expected move clears this percentile of the median's
# own historical magnitude. Late in a candle the band is narrow and the model is confident
# about a move too small to act on; without a floor those rows dominate the calls. The
# floor is per horizon and measured from the data at build time, so it grows with the
# history rather than being asserted, and it moves slowly because it is a percentile over
# everything seen so far. Raising it trades volume for reliability, and the hit rate
# responds monotonically - see docs/RESULTS.md for the measured curve. Per horizon
# because the curve is shaped differently on each: weekly gains a lot from being
# selective, daily gains almost nothing and pays for it in volume.
MIN_MOVE_PERCENTILE = {"daily": 0.50, "weekly": 0.75, "monthly": 0.75}

# Nominal interval coverage implied by the band [Q10, Q90]. Used by evaluation to
# compare realized coverage against the target. Acceptable realized range is 80-85%.
NOMINAL_COVERAGE = 0.80

# ----------------------------------------------------------------------------------
# History depth per horizon (start date of training data)
# ----------------------------------------------------------------------------------
# Daily and weekly start around 2010 (older daily data is noisier). Monthly reaches
# as far back as possible so the model can see crash events (2000, 2008) that teach
# the lower tail (Q10).
HISTORY_START = {
    "daily": "2010-01-01",
    "weekly": "2010-01-01",
    "monthly": "1993-01-01",
}

# ----------------------------------------------------------------------------------
# Indicator parameters and conventions (must match the backend extractor exactly)
# ----------------------------------------------------------------------------------
MA_PERIODS = [20, 50, 100, 150, 200]   # SMA and EMA periods
BB_PERIOD = 20                          # Bollinger period (base is the 20-period SMA)
BB_K = 2.0                              # Bollinger band width in sigma
RSI_LENGTH = 14                         # Wilder RSI length
VOLUME_AVG_WINDOW = 90                  # window behind volume_avg_daily_90
MACD_FAST = 12                          # MACD fast EMA span
MACD_SLOW = 26                          # MACD slow EMA span
MACD_SIGNAL = 9                         # MACD signal-line EMA span
ATR_LENGTH = 14                         # Wilder ATR length
STOCH_PERIOD = 14                       # Stochastic look-back
STOCH_K_SMOOTHING = 3                   # Stochastic %K smoothing
STOCH_D_SMOOTHING = 3                   # Stochastic %D smoothing

# Rolling window (in rows) for realized volatility per horizon.
# IMPORTANT: every pct_change_* column is already in percentage points (times 100),
# so realized volatility must NOT be multiplied by 100 again.
REALIZED_VOL_WINDOW = {"daily": 21, "weekly": 13, "monthly": 12}

# Approximate number of trading days inside a candle, used for the days_to_close
# fraction. Daily has no time_to_close because it always forecasts a full next-day candle.
TRADING_DAYS_PER_CANDLE = {"weekly": 5, "monthly": 21}

# ----------------------------------------------------------------------------------
# Splitting and cross-validation
# ----------------------------------------------------------------------------------
# Fraction of each ticker's candle groups held out for the final test set. Held out
# per ticker and time-ordered, so every index is represented in proportion and the
# test period is the most recent (no look-ahead).
TEST_SIZE = 0.20

# Number of GroupKFold folds used for validation and tuning on the train set.
# Lidor's call: 5 or 6. Groups are whole candles, so no candle straddles a fold.
N_SPLITS = 5

# Embargo gap (in candle groups) between folds. Adjacent candles share long look-back
# windows, so a strict setup would leave a small gap between train and validation.
# Disabled by default for this course project. Flagged as a future improvement.
EMBARGO_GROUPS = 0

# ----------------------------------------------------------------------------------
# Reproducibility and plotting
# ----------------------------------------------------------------------------------
RANDOM_SEED = 42
PLOT_DPI = 130

# ----------------------------------------------------------------------------------
# Helper column names (used only to build the label, never fed to the model)
# ----------------------------------------------------------------------------------
# The current daily close at each row's date. It is the universal anchor for both the
# label denominator ("last known daily close") and the relative feature engineering
# (the running close, consistent with the intra-candle convention). Dropped before training.
ANCHOR_CLOSE = "anchor_close_daily"

# Candle id used for grouping (split and cross-validation). For a row rolled over
# to the next candle, this is the NEXT candle's id - the candle where its label
# realizes - so a group can never straddle the train/test boundary through a label.
LABEL_PERIOD_COLUMN = "label_period"


# Shared columns carried into every horizon dataset.
SHARED_COLUMNS = ["Date", "ticker", ANCHOR_CLOSE]

# Column name of the regression label per horizon. Expressed in percentage points
# (for example 1.5 means a +1.5% move), to match the scale of the pct_change features.
def target_column(horizon: str) -> str:
    """Return the label column name for a horizon, for example 'target_daily'."""
    return f"target_{horizon}"


# ----------------------------------------------------------------------------------
# Model path helpers (pure path construction, no heavy imports)
# ----------------------------------------------------------------------------------
def dev_model_path(horizon: str, qname: str) -> pathlib.Path:
    """Stage-2 development booster path: dev_models/<horizon>/<quantile>.txt."""
    path = DEV_MODELS_DIR / horizon / f"{qname}.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def inference_model_path(horizon: str, qname: str) -> pathlib.Path:
    """Final production booster path: Inference_models/<horizon>/<quantile>.txt."""
    path = INFERENCE_MODELS_DIR / horizon / f"{qname}.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def inference_metadata_path(horizon: str) -> pathlib.Path:
    """Production metadata path: Inference_models/<horizon>/metadata.json."""
    path = INFERENCE_MODELS_DIR / horizon / "metadata.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path