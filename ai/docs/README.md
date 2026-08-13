# 🧠 AI — Quantile Forecasting Engine

This directory owns everything from raw candles to the production boosters the backend serves. The model predicts a **percent-change band** — not a price, and not a direction.

> System overview: [`../../README.md`](../../README.md) · Backend contract: [`../../backend/docs/README.md`](../../backend/docs/README.md) · Measured results: [`RESULTS.md`](./RESULTS.md)

---

## 📑 Table of Contents

- [Design in One Page](#-design-in-one-page)
- [What the Model Reads](#-what-the-model-reads)
- [Pipeline Stages](#-pipeline-stages)
- [Leakage Protections](#-leakage-protections)
- [Rollover Labeling](#-rollover-labeling)
- [Calibration](#-calibration)
- [Stability, Not Confidence](#-stability-not-confidence)
- [From Band to Recommendation](#-from-band-to-recommendation)
- [Hyperparameter Tuning](#-hyperparameter-tuning)
- [Contracts the Backend Uses](#-contracts-the-backend-uses)
- [Directory Map](#-directory-map)
- [Runbook](#-runbook)
- [Results](#-results)

---

## 🎯 Design in One Page

**Nine boosters.** Three quantiles (`Q10`, `Q50`, `Q90`) × three horizons (`daily`, `weekly`, `monthly`). All tickers are **pooled** into one model per horizon, with `ticker` passed as a categorical feature and per-ticker sample weighting.

**Rows are not observations.** Every horizon is built from the same daily rows, so a monthly candle contributes about 21 highly correlated rows and a weekly one about 5. The monthly table therefore holds the *most* rows and the *fewest* independent candles. Folds, groups and every judgement about how much data a horizon has are counted in candles, never in rows — `results/tables/split/split_summary.csv` reports both.

**One label, three models.** Every booster trains on the same target — percent change × 100. The three quantiles emerge *solely* from the asymmetric **pinball loss** `alpha` (0.10 / 0.50 / 0.90). There is no separate "upper" or "lower" label.

**Full retrain, always.** Gradient-boosted trees cannot be continued the way a neural network can. Each newly closed candle triggers a rebuild from scratch for that horizon.

**No normalization.** Trees are scale-invariant. Raw price levels never enter the model — only relative features do. See [`FEATURES.md`](./FEATURES.md).

| Choice | Why |
|---|---|
| LightGBM on **CPU** | At tens of thousands of rows, OpenCL kernel-compile and transfer overhead costs more than the GPU saves |
| History from **2010** (daily/weekly), **1993** (monthly) | The monthly model needs crash events to learn its lower tail |
| Percent change as target | Comparable across tickers whose price levels differ by orders of magnitude |
| Indices only, no single stocks | Pooling assumes homogeneity; meme stocks break it |
| `deterministic` fits | The same data and seed must give the same booster on a laptop and on 32 cluster cores, or a tuned parameter set does not reproduce |

Set `ALGOTRADE_LGBM_DEVICE=gpu` to force the GPU path.

---

## 📚 What the Model Reads

A band is a claim about **dispersion**, so the feature set is built around the question "how far is this index likely to travel", not only "which way". Four families answer it, and each horizon carries its own version of all four.

| Family | Columns | What it contributes |
|---|---|---|
| **Trend position** | `dist_sma_*`, `dist_ema_*`, `bb_pctb_*`, `macd_pct_*`, `macd_hist_pct_*` | Where the close sits relative to its own history, and how fast that is changing |
| **Volatility** | `atr_pct_*`, `bb_width_*`, `realized_vol_*`, `range_pct_*` | How wide this index's candles have actually been — the most direct evidence about band width |
| **Participation & position** | `rel_vol_*`, `rsi_*`, `rsi_gap_*`, `stoch_k_*`, `stoch_d_*`, `stoch_gap_*` | Whether the move is crowded, and whether the index is stretched inside its recent range |
| **Macro regime** | `vix_*`, `tnx_*`, `irx_*`, `dxy_*`, `term_spread_*`, `*_chg_*` | The state of the wider market: implied volatility, the yield curve, the dollar |

The macro family is the one that is not derived from the ticker at all. Implied volatility is the market's own forward estimate of dispersion, which is precisely the quantity a band is trying to produce; the yield curve and the dollar set the regime that estimate lives in. Levels say which regime we are in, and the candle-over-candle change says whether it is deteriorating.

**Own price levels are excluded; exogenous levels are not.** MACD and ATR arrive from the backend in the ticker's own currency, so they are divided by the anchor close first — an ATR of 6 means something different on TA35 than on SPY, and something different again twenty years apart. A VIX level or a Treasury yield is exogenous and range-bound over the sample, so it enters unchanged.

**Shorter horizons see longer-horizon state.** The daily model reads the weekly and monthly ATR and implied volatility; the weekly model reads the monthly ones. A calm day inside a turbulent month is not the same forecast as a calm day inside a calm month. `config.CONTEXT_COLUMNS` decides what crosses, and everything listed there is known at the row's close.

---

## 🔧 Pipeline Stages

Run everything with `python runners/run_pipeline.py`.

### [`1_PreTraining/`](../1_PreTraining/README.md) — data → features → splits

| Script | Does |
|---|---|
| `Data-Extraction/extract_dataset.py` | Reads the backend SQLite store, joins the three horizon tables per ticker, pools them |
| `Feature-Eng/check_missing.py` | Reports NaNs; drops only rows with no anchor close |
| `Feature-Eng/build_features.py` | Builds relative features and the label, drops raw prices |
| `Feature-Eng/split_dataset.py` | Group-aware train/test split on a **global date cutoff** |
| `Feature-Eng/run_eda.py` | Correlation heatmaps and mutual-information reports — **train split only** |

Feature NaNs are deliberately **kept**: LightGBM routes missing values natively, and imputing them would invent data.

**The extraction adapter owns the naming contract.** The backend names its exogenous series after their yfinance symbol (`^VIX_daily_last`, `DX-Y.NYB_weekly_last`). `load_raw_ticker_table` renames them to the prefixes in `config.SUPPORT_SERIES_PREFIX` on the way in, so no spec downstream carries a caret or a dot. `validate_pooled` then checks every indicator the AI expects and **warns by name** for anything absent — a feature whose source column does not arrive is otherwise dropped in silence, because `build_features` only keeps the passthrough columns it can actually find.

### [`2_Train/`](../2_Train/README.md) — train and evaluate

Trains each horizon's three quantiles with early stopping on chronological folds, then evaluates on the held-out test split against a naive baseline.

Reported per horizon: `coverage`, `width`, `dir_acc`, per-quantile pinball, and an **interval score** measured against a per-ticker empirical-quantile baseline. A model that cannot beat that baseline has found no signal.

### [`3_Production-FinalTraining/`](../3_Production-FinalTraining/README.md) — refit and ship

| Script | Does |
|---|---|
| `build_final_models.py` | Refits on **train + test combined**, writes `Inference_models/<horizon>/` |
| `verify_inference.py` | Smoke test — loads the models, predicts once, asserts the band is valid |
| `predictor.py` | `predict_latest(ticker, horizon)` — the function the backend calls |

Each `metadata.json` carries `feature_columns`, `width_grid`, and `last_trained_through`. **It is written last**, so its presence guarantees the boosters beside it are complete.

Evaluation formulas live in [`../Evaluation/README.md`](../Evaluation/README.md).

---

## 🔒 Leakage Protections

Each of these is load-bearing. Removing any one silently corrupts the evaluation.

- **Global date cutoff for the split.** A per-ticker holdout leaks: six correlated indices share market-wide shocks, so one ticker's future can surface in another's training data. The cutoff is a single date, applied to all.
- **Chronological expanding-window folds.** `time_ordered_group_folds` in [`../utils/modeling.py`](../utils/modeling.py) orders candle groups by start date and validates block *k* on a model trained only on blocks 0…*k*−1. A plain `GroupKFold` would train on the future.
- **Grouping by `label_period`, not the calendar period.** A rolled-over row (below) predicts the *next* candle, so it must be grouped with that candle — otherwise its label crosses the split.
- **Per-candle windows, not per-row.** Weekly and monthly columns that describe a closed candle repeat across intra-candle rows. Every rolling or differencing feature routes through `per_candle_transform`, so a window of thirteen weeks reads thirteen weeks and not thirteen rows of the same week.
- **Exogenous series enter lagged.** The backend supplies each macro series as the *last closed* value for the horizon, so a row never reads a VIX print from its own unfinished candle.
- **EDA on the train split only.** Inspecting test-set correlations is leakage through the researcher.
- **`Date`, `group_id`, and `label_period` are never features.** Enforced by `NON_FEATURE_COLS`.

---

## 🔁 Rollover Labeling

The last trading row of a weekly or monthly candle has an in-candle target of exactly zero, by construction — the candle closes on that row. Training on such rows teaches the model that Fridays don't move.

Dropping them would leave no weekend forecast. Instead they are **relabeled**:

| | Raw row | After rollover |
|---|---|---|
| Target | 0 (degenerate) | Percent change to the **next** candle's close |
| `days_to_close` | 0 | 1.0 |
| `label_period` | Current candle | **Next** candle |

Inference mirrors this exactly (`predictor.py`), so a Friday-evening weekly forecast is a forecast of next week — which is what a user actually wants.

---

## 🎚️ Calibration

A band fitted by pinball loss is sharp but not calibrated: nothing in the objective
forces 80% of outcomes inside it, and the recent past is rarely as turbulent as the
period a model was fitted on. Two mechanisms close that, and both are part of the
model rather than a correction bolted on after.

**The label is standardised by volatility.** Each horizon's label is divided by a
backward-looking volatility estimate before fitting, and the scale is multiplied back
at prediction. A crash month and a calm month are the same shape once each is divided
by its own volatility, so one model can describe both, and the band widens in
turbulence by construction instead of relying on the trees to infer the magnitude.
`config.VOLATILITY_SCALE_COLUMNS` picks the column, preferring realised volatility and
falling back to ATR%.

**The band is conformalised.** The most recent `CALIBRATION_SIZE` of the training
candles is held back, the model is fitted without them, and the distance by which the
band misses on them is measured. The (1−α) quantile of those distances is the smallest
widening that would have covered the required share — and because those rows were never
trained on, it carries a finite-sample coverage guarantee rather than a hope. The
offset is applied on the standardised scale, so the widening it produces is
proportional to each row's own volatility.

**Calibration is per position in the candle.** A weekly row with four days left faces a
band roughly twice as wide as one with a day left, and a single offset cannot serve
both — it leaves the opening of the candle under-covered and its close over-covered.
`CALIBRATION_BUCKETS` splits the calibration slice by days-to-close and measures an
offset within each, so every stretch of the candle answers for itself. The offsets are
printed at build time and stored in `metadata.json`; the `days_to_close` rows of
`results/metrics/test_<horizon>/coverage_breakdown.csv` show whether they worked.

The daily horizon always forecasts one whole candle ahead, so it has no position and
collapses to a single bucket.

The calibration slice is the **most recent** stretch on purpose: a correction fitted on
the newest data tracks the regime the next forecast will be made in.

> This is not the width multiplier fitted on validation that [`../Evaluation/README.md`](../Evaluation/README.md) argues against. That widens every band by the same factor regardless of conditions, buying the coverage statistic by making the forecast less sharp. Here the widening scales with the row, and the amount is measured on data the model never saw rather than tuned until the number looks right.

---

## 📊 Stability, Not Confidence

Two numbers that are easy to confuse:

| | What it is | Varies? |
|---|---|---|
| **The 80% level** | What the band promises: 80% of outcomes fall inside it | Fixed. Always Q10–Q90 |
| **`stability` (0–1)** | How narrow today's band is versus this horizon's historical band widths | Every day |

A narrow band means a calm market and scores high. A wide band means turbulence and scores low. **Both still promise 80%.** The percentile grid used for the ranking lives in each `metadata.json` as `width_grid`.

---

## 🧭 From Band to Recommendation

The band says how far the market might travel. The recommendation says which way to lean,
and it is derived from the band in three steps.

### 1. The band becomes a probability

Q10, Q50 and Q90 are three points on the outcome's cumulative distribution, at 0.10, 0.50
and 0.90. Interpolating between them gives the distribution's value at zero, and one minus
that is **`prob_up`** — the chance the next move is positive.

This is the median expressed in units of the band's own width. A `+0.4%` median inside a
turbulent `−6% … +6%` band gives `prob_up = 0.525`; the same median inside a calm
`−1% … +1%` band gives `0.614` (both follow directly from the interpolation above).
Same forecast, very different conviction — one number carries both.

Note what zero means on the longer horizons. A weekly row's label is the move **remaining**
from that row's close to the week's close, not the whole week's move, and
`pct_change_week_current` tells the model how much has already happened. So `prob_up` on a
Wednesday is the chance the *rest of the week* finishes higher than where it stands now.

The interpolation reads the distribution rather than assuming a shape, which matters
because the median is not pinned to the middle of the band — a skewed band leans, and
`prob_up` leans with it.

### 2. A move floor, then a margin around a coin flip

```
eligible  |Q50| >= move_floor
Long      eligible and prob_up >= 0.5 + margin
Short     eligible and prob_up <= 0.5 - margin
Stay-out  everything else
```

The **move floor** exists because confidence and size are different things. Late in a
candle the band is narrow and the model is genuinely confident — about a move far too
small to act on. Without a floor those rows take over the calls. It is a percentile of
the median's own historical magnitude (`MIN_MOVE_PERCENTILE`), so it is measured from
the data rather than asserted, differs per horizon, and moves slowly as history grows.

**The anchor is 0.5, not the distribution's own centre.** Cutting at the top and bottom
percentiles instead would hand out as many Shorts as Longs by construction — and on a
market that has risen for thirty years, the only way to fill a Short quota is to
manufacture Short calls from setups that are merely *less bullish than average*. Anchoring
on 0.5 asks a real question, and lets the mix land where the data puts it. A horizon that
drifts upward produces mostly Longs. That is the finding, not a bias to correct.

### 3. The margin is measured, not guessed

An absolute threshold cannot work here, because how confident this model can *ever* be is a
property of the data, not something knowable in advance. Ask for `prob_up > 0.90` — which
is what "the whole 80% band clears zero" means — and nothing ever qualifies, so every row
collapses to Stay-out.

So `config.RECOMMENDATION_RATE` states the share of rows that should receive a direction,
and the margin is sized from the model's own distribution of `prob_up` to deliver it.

**The margin is fitted per position bucket, like the calibration.** The spread of
`prob_up` widens as a candle nears its close, purely because the band tightens — so a
single margin hands out most of its calls at the end of the candle and almost none at
the start. One margin per bucket keeps the rate steady from open to close.

A forecast made mid-candle is therefore judged against what is actually knowable at that
point, not against a standard set by rows with far less uncertainty left. The call is
re-made on every new close and is free to change as the candle fills in — an early Long
becoming a Stay-out, or a late Short, is the rule working rather than failing.

The build stage measures the floor and the margins over the full history and stores them
in `metadata.json`; they are re-measured on every retrain, so they track the data as it
grows.

> Grading on a curve rather than against a fixed pass mark. If the top score in the class is
> 71, "above 90 gets an A" identifies nobody — including the best student.

### Choosing the rate

The rate is a **decision**: how often do you want an opinion. Whether those opinions are any
good is a separate **measurement**, and the two must not be confused. Every evaluation run
writes `results/metrics/test_<horizon>/recommendation_sweep.csv`, listing the hit rate at
each candidate rate:

| Column | Meaning |
|---|---|
| `rate` | The candidate value of `RECOMMENDATION_RATE` |
| `move_floor` | The magnitude gate that rate implies |
| `fired_share` | Share of rows that actually received a direction |
| `n_long` / `n_short` | How the calls split |
| `hit_rate` | Of the calls made, the share that moved that way |
| `edge` | `fired_share × (hit_rate − 0.5)` |
| `best_by_edge` | Marks the row with the highest edge |

A hit rate that falls as the rate rises is the signature of a real ranking: the most
extreme setups are the most reliable. A hit rate that sits flat at 0.5 means the ranking
carries no directional information, and **no choice of rate will rescue it** — set the rate
to `0.0` for that horizon and show only the band.

**`edge` picks the default.** Hit rate alone always rewards being more selective, right down
to never calling anything, so it cannot choose a rate on its own. `edge` is
`fired_share × (hit_rate − 0.5)`: the share of all rows that are correct calls beyond what
a coin flip gives. A high hit rate on a handful of rows can be worth less in total than a
slightly lower one on many, and this is the column that says so. Take the `best_by_edge`
row unless there is a reason to prefer fewer, more confident calls.

---

## 🎛️ Hyperparameter Tuning

Optuna, in [`../tuning/tune_core.py`](../tuning/tune_core.py). **One study per horizon** — not nine — because a horizon's three quantiles share hyperparameters; only the pinball `alpha` differs, and that is not a hyperparameter.

**Objective:** mean out-of-fold pinball across the three alphas, on the same chronological folds training uses.

> Why not coverage? The easiest way to reach 80% coverage is an absurdly wide band. Pinball is a *proper scoring rule*: it penalizes width and misses at once. Coverage is what we check afterwards, not what we optimize — every trial records its realized `coverage` and `mean_band_width` as user attributes, and the winning pair is printed at the end of the run, so the trade-off is visible without ever entering the objective.

**The search space is conditional.** `num_leaves` is drawn *after* `max_depth` and capped at `2**max_depth`, because a tree of depth *d* cannot hold more leaves than that. Sampled independently, a trial can carry a leaf count its depth makes unreachable, and the sampler then attributes the score to a knob that never took effect. The sampler is multivariate TPE with grouping, which is built for exactly this kind of dependent space.

```bash
# Local, single horizon
python ai/tuning/tune_daily.py 600

# Cluster (BGU SLURM) — one job per horizon
sbatch ai/tuning/sbatch/tune_daily.sbatch
```

Studies persist to SQLite in `tuning/studies/`, so a killed job resumes where it stopped. Winners are written to `tuning/best_params/<horizon>.json`, and [`../utils/modeling.py`](../utils/modeling.py) **merges them over the hand-set baselines automatically** on the next training run — nothing to copy by hand.

`best_params` is rewritten **the moment a new best trial lands**, not when the run finishes. A three-day cluster job is exactly the kind that gets pre-empted, and the file on disk is always the best configuration found so far — a study can be stopped or resubmitted at any point without losing the winner.

**A study is only extended under the conditions it was searched in.** Optuna resumes across a changed feature set or a changed search space without complaint, and would then report a best trial whose parameters no longer mean what they meant. `check_study_is_compatible` compares the stored feature count and parameter names against the current ones and stops with the exact `rm` command when they differ. Changing the feature set or the search space therefore means starting a fresh study — the old trials are not comparable and averaging them in would corrupt the search.

**Tuned parameters are bound to a feature set.** A study optimizes `colsample_bytree`, `num_leaves` and the round count for the width of the matrix it saw, so those values stop meaning what they meant once features change. Each winner therefore records the `n_features` it was searched on, and `check_tuned_against_features` prints a warning at training time when that count no longer matches the data. The booster still trains — it is simply no longer running on a searched configuration.

> After pulling new `best_params`, run `run_pipeline.py` once so `cv_summary.json` — which drives the final round count — reflects the tuned parameters.

---

## 🔌 Contracts the Backend Uses

Both are loaded by file path from `backend/ai_bridge/`, because the stage folders are not importable packages.

```python
# 3_Production-FinalTraining/predictor.py
predict_latest(ticker, horizon) -> {
    "low", "mid", "high",   # percent points, calibrated
    "stability",            # 0..1, how narrow versus this horizon's history
    "prob_up",              # 0..1, P(next move > 0)
    "recommendation",       # "Long" / "Short" / "Stay-out"
    "based_on_date",        # last closed candle
}

# utils/model_status.py  (read-only, no side effects, safe to poll)
is_ready() -> bool
full_status() -> {"ready": bool, "horizons": [...]}
```

`is_ready()` compares each model's `last_trained_through` against the newest candle in the feature store. A **date comparison, never a stored flag** — so it cannot go stale.

---

## 🗂️ Directory Map

| Path | Contents |
|---|---|
| `config.py` | Every constant: tickers, horizons, quantiles, paths, history depth, indicator parameters, the exogenous-series name map |
| `utils/features.py` | All feature builders, `per_candle_transform`, and the canonical `period_id` — the single source of truth |
| `utils/modeling.py` | Params, folds, dataset construction, volatility scaling, conformal calibration, tuned-param guard |
| `utils/model_status.py` | The readiness check |
| `utils/log.py` | Colored logging, sharing the backend's `ConsoleLogger` |
| `utils/gpu.py` | Device selection (CPU by default) |
| `utils/io_store.py` | Parquet read/write for every intermediate table |
| `Evaluation/metrics.py` | Pinball, interval score, coverage breakdowns |
| `runners/run_pipeline.py` | Stages 1 → 2 → 3, with per-step timing |
| `data_store/` 🚫 | Intermediate parquet (generated) |
| `dev_models/` 🚫 | Evaluation boosters (generated) |
| `Inference_models/` 🚫 | Production boosters, rebuilt by the code (generated) |
| `results/` 🚫 | Metrics, plots, reports (generated) |

Model files are plain `.txt` — LightGBM's native format. Every tree, split, and leaf value is written out in full. A tree model *is* its trees; there are no binary weight matrices to serialize.

---

## ▶️ Runbook

```bash
# Full pipeline — train, evaluate, rebuild production models
python ai/runners/run_pipeline.py

# One tuning study
python ai/tuning/tune_weekly.py 600
```

The pipeline reads the backend's SQLite store directly, so the data must be synced first — `python bootstrap.py` handles it, and so does `train_service`.

## 📊 Results

Coverage, interval score against the naive baseline, calibration offsets, and the
directional hit rate for the current model are in [`RESULTS.md`](./RESULTS.md), together
with what does not work yet. That file is a snapshot of one run; this one is the design.

### Reading a coverage shortfall

Coverage below the 0.80 target means the bands are too narrow, and there are two very different reasons that happens.

1. **The model cannot see the dispersion.** Check `results/metrics/test_<horizon>/coverage_breakdown.csv`, which reports coverage and width per ticker, per year, and per days-to-close bin. If one index or one turbulent stretch sits far below the rest, the band is not responding to conditions it has no feature for. That is a feature problem and it is fixed with features.
2. **The model sees it but is not using it.** Check the tuned `coverage` user attribute against the test coverage, and the mutual-information report in `results/tables/eda/`. If the volatility features rank high and coverage is still flat, the search space or the round count is the constraint.

Read `coverage_breakdown.csv` before changing anything. The
calibration described above targets the *average* miss; if one index or one turbulent
stretch sits far below the rest, the band is not responding to a condition it has no
feature for, and that is a feature problem no calibration will fix.