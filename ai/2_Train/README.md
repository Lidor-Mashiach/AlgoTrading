# 🏋️ Train

This folder trains the quantile boosters and evaluates them on the held-out test split. It
reads the splits produced by PreTraining and writes development boosters plus evaluation
results.

Run it with `run_train.py`, which trains every horizon and then evaluates every horizon.
Training comes first because the test stage loads the boosters that training produces.

---

## 🧩 Structure

A shared engine holds all the logic. The per-horizon scripts are thin wrappers that send
their horizon to the engine. This avoids duplicating training code three times while still
giving each horizon its own entry point and its own results folder.

| File | Role |
| --- | --- |
| `train_core.py` | Stage-2 engine: cross-validation, sample-weighted refit, learning curves, saving |
| `train_daily.py`, `train_weekly.py`, `train_monthly.py` | Thin wrappers, one call each |
| `test_core.py` | Shared evaluation engine: predictions, metrics, and figures |
| `test_daily.py`, `test_weekly.py`, `test_monthly.py` | Thin wrappers, one call each |
| `test_baseline.py` | The naive per-ticker quantile band, run on the same test split |

The per-horizon hyperparameters and the low-level fit helpers live in `../utils/modeling.py`,
which both this stage and stage 3 import, so neither stage depends on the other.

Within a horizon, the wrapper loops over Q10, Q50, and Q90 and sends each to the engine. The
three quantiles share the same features and the same label and differ only in the pinball
alpha.

---

## 🔁 How training works

- **Categorical ticker.** The index identity enters as a native categorical feature with a
  fixed category list, so train, test, and inference share the same mapping.
- **Sample weights.** Weights balance the indices, so an index with a long history does not
  dominate one with a short history.
- **Cross-validation.** Expanding-window folds over whole candles: the candle groups are
  ordered by start date, cut into contiguous blocks, and block *k* is validated on a model
  trained only on blocks 0…*k*−1. No fold ever trains on data later than its validation, and
  because the group is the candle, no candle leaks between fold train and validation. The
  folds also choose the number of boosting rounds.
- **Final fit.** Each quantile is refit on the full train split for the chosen number of
  rounds and saved as a development booster.

Per-quantile pinball loss is the fold metric, because the band metrics such as coverage need
Q10 and Q90 together and belong to the test stage.

Every run prints the feature count it is training on, and warns when the stored tuned
parameters were searched against a different one — a study optimizes `colsample_bytree`,
`num_leaves` and the round count for the matrix width it saw.

---

## 🖥️ GPU and CPU

LightGBM uses OpenCL through `device="gpu"`, and that build is often missing from a plain
install. The pipeline tries a tiny GPU fit once and falls back to the CPU if it fails, so it
runs anywhere without configuration. The decision is cached for the process.

Fits are `deterministic` with `force_row_wise`, so the same data and seed reproduce the same
booster whether the run happens on a laptop or on 32 cluster cores.

---

## 📊 Evaluation

The test stage loads the three development boosters for a horizon, predicts the band on the
held-out test split, and writes coverage, mean band width, the interval score, pinball loss
per quantile, the Q50 errors, directional accuracy, and the directional confusion matrix.
See `../Evaluation/README.md` for what each metric means and why it was chosen.

Coverage and width are also written to `coverage_breakdown.csv`, broken down **per
ticker, per year, and per days-to-close bin**. A global coverage number can sit on target while one index or one
turbulent year sits far below it, and that breakdown is the first thing to read when
coverage disappoints — it separates "the band ignores conditions it cannot see" from "the
band is uniformly a little tight".

Figures saved per horizon: the predicted interval against the realized moves, the confusion
matrix, and the Q50 residual distribution.

The measured outcome of the latest run is in [`../docs/RESULTS.md`](../docs/RESULTS.md).

`test_baseline.py` runs last and scores a band that uses no features at all: the empirical
10th, 50th and 90th percentiles of each ticker's own training labels. The boosters have to
beat it, mainly on the interval score, or the feature engineering bought nothing.

---

## 📤 Outputs

- Development boosters into `dev_models/<horizon>/<quantile>.txt`. These are kept separate
  from the production models in `Inference_models/` and exist only so the test stage, which
  is a separate script, can load what the train stage produced.
- Training results: `results/plots/train_<horizon>/<quantile>/` for the learning curve and
  `results/metrics/train_<horizon>/<quantile>/` for the cross-validation summary.
- Test results: `results/plots/test_<horizon>/` for the figures,
  `results/metrics/test_<horizon>/` for the metric values, the per-quantile pinball, and the
  coverage breakdowns, and `results/reports/test_<horizon>/` for the short readable report.

Only the latest run is kept.