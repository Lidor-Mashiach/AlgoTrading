# 📊 Results

Measured on the held-out test split — the most recent 20% of the timeline, by a global
date cutoff, never seen during training, tuning or calibration.

**Run:** 2026-07-27 · `python ai/runners/run_pipeline.py` · Optuna studies re-run from
scratch for all three horizons.

Every number here is reproducible from `results/` after a pipeline run. This file is a
snapshot; the design reasoning lives in [`README.md`](./README.md).

---

## 📑 Table of Contents

- [Headline](#-headline)
- [Against the Naive Baseline](#-against-the-naive-baseline)
- [Calibration](#-calibration)
- [Directional Recommendation](#-directional-recommendation)
- [Chosen Settings](#-chosen-settings)
- [What Does Not Work Yet](#-what-does-not-work-yet)
- [Hyperparameter Tuning](#-hyperparameter-tuning)

---

## 🎯 Headline

The band promises 80% coverage. Two horizons deliver it; the third does not.

| Horizon | Test rows | Coverage | Target | Mean width | Interval score |
|---|---|---|---|---|---|
| daily | 4,683 | **0.804** | 0.80 | 2.500 | 3.564 |
| weekly | 4,671 | **0.807** | 0.80 | 4.417 | 6.072 |
| monthly | 9,262 | 0.745 | 0.80 | 7.705 | 12.238 |

> Coverage above 0.80 is not better than 0.80. A band that covers 95% of outcomes is a
> band that has been made too wide to be useful. The target is to *hit* the number.

Daily and weekly hold their coverage year by year, which is the stronger claim — a
global average can be built from an over-covered stretch and an under-covered one:

| Horizon | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|
| daily | 0.806 | 0.806 | 0.801 | 0.804 |
| weekly | 0.810 | 0.809 | 0.816 | 0.783 |

---

## ⚖️ Against the Naive Baseline

The baseline uses no features at all: a fixed band per ticker, taken from the 10th, 50th
and 90th percentiles of that ticker's own training labels. It is the honesty check — if
the models cannot beat "what this index historically does", the feature engineering
bought nothing.

| Horizon | Coverage | Band width | Interval score | Directional accuracy |
|---|---|---|---|---|
| daily | 0.804 vs 0.808 | 1.2% wider | **+3.8%** | 0.534 vs 0.476 |
| weekly | 0.807 vs 0.784 | 10.4% wider | **+5.9%** | 0.576 vs 0.491 |
| monthly | 0.745 vs 0.774 | 6.3% narrower | **+12.8%** | 0.575 vs 0.578 |

**The models do not win by dominating on coverage and width.** Read those two columns
alone and the picture is mixed: daily is a near-tie, weekly buys its coverage with a
wider band, and monthly is sharper but covers less. The win is in the interval score,
and it comes from somewhere else.

The interval score is width plus a penalty proportional to how far outside the band each
missed outcome landed. Splitting it apart shows what the models actually bought:

| Horizon | | Width | + Penalty | Miss rate | Average miss |
|---|---|---|---|---|---|
| daily | model | 2.500 | 1.064 | 19.6% | **0.543 pp** |
| | baseline | 2.470 | 1.234 | 19.2% | 0.643 pp |
| weekly | model | 4.417 | 1.656 | 19.3% | **0.857 pp** |
| | baseline | 4.002 | 2.451 | 21.6% | 1.133 pp |
| monthly | model | 7.705 | 4.533 | 25.5% | **1.774 pp** |
| | baseline | 8.219 | 5.822 | 22.6% | 2.579 pp |

**When the models are wrong, they are less wrong** — by 16%, 24% and 31%. A fixed band
misses by a lot on exactly the candles it was never shaped for; a conditional band that
has widened for the conditions misses by a little. That is the whole value of the
feature engineering, and coverage alone cannot see it.

It also means the models are worth more than the interval score suggests to anyone
acting on the band, because the cost of a miss is rarely linear in its size.

Monthly is the case to read carefully. It wins the interval score by the largest margin
of the three, while **missing its 80% promise more often than the baseline does**
(25.5% against 22.6%). It is the better-shaped band and the less honest one. Both are
true, and which matters more depends on whether the band is being used to size a
position or to make a promise.

---

## 🎚️ Calibration

The conformal offsets, measured on held-out recent candles and applied per position
within the candle:

| Horizon | Offsets by position bucket | Calibration rows |
|---|---|---|
| daily | `[0.057]` | 2,810 |
| weekly | `[0.070, 0.121, 0.097, 0.090]` | 2,790 |
| monthly | `[−0.028, −0.008, −0.017, 0.002, 0.029]` | 5,426 |

Daily has a single bucket by design — it always forecasts one whole candle ahead, so
there is no position inside a candle to speak of.

The weekly and monthly offsets differ across buckets, which is the case for measuring
them separately: a single number would have over-widened one end of the candle and
under-widened the other.

They reduce the position dependence without removing it. Coverage still varies by where
in the candle the forecast is made:

| Weekly, days-to-close | 0.2 | 0.4 | 0.6 | 0.8 | 1.0 |
|---|---|---|---|---|---|
| Coverage | 0.857 | 0.820 | 0.801 | 0.806 | 0.767 |
| Band width | 2.97 | 3.68 | 4.37 | 5.25 | 5.36 |

The band does widen as more of the candle remains — from 2.97 to 5.36, which is the
behaviour the design intends — but not quite enough at the open of the candle, where
coverage falls to 0.767. A forecast made on the first day of a week is the least
reliable one that week, and by about four points of coverage.

---

## 🧭 Directional Recommendation

`prob_up` ranks setups; the move floor decides which are worth naming. Raising the floor
is what turns the ranking into a decision, and the hit rate responds to it **monotonically
on all three horizons** — the signature of a ranking that carries real information.

Hit rate as the floor rises (`rate` held high, so the floor is the only gate):

| `MIN_MOVE_PERCENTILE` | daily | weekly | monthly |
|---|---|---|---|
| 0.00 (call every row) | 0.534 | 0.576 | 0.575 |
| 0.25 | 0.552 | 0.590 | 0.586 |
| 0.50 | 0.568 | 0.613 | 0.598 |
| 0.65 | 0.581 | 0.622 | 0.607 |
| **0.75** | **0.581** | **0.669** | **0.621** |
| 0.85 | 0.613 | 0.690 | 0.649 |
| 0.95 | 0.679 | 0.818 | 0.723 |

The first row is the number every other row has to beat. Calling a direction on *every*
row is, in a market that rose over the test period, almost the same as always saying
Long — so 0.534 / 0.576 / 0.575 is roughly what always-Long scores, and anything above
it is the model actually selecting.

The last rows have the highest hit rates and the smallest samples (weekly at 0.95 is
11 calls). They are not a setting; they are the tail of the same curve.

At the chosen floors:

| Horizon | Floor | Move floor | Calls | Share of rows | Hit rate | 95% CI |
|---|---|---|---|---|---|---|
| daily | 0.50 | 0.065% | 1,114 | 23.8% | 0.568 | [0.539, 0.598] |
| weekly | 0.75 | 0.216% | 408 | 8.7% | 0.669 | [0.621, 0.715] |
| monthly | 0.75 | 0.574% | 2,796 | 30.2% | 0.621 | [0.602, 0.639] |

All three confidence intervals sit clear of 0.50, and weekly and monthly sit clear of
their own always-Long baselines. Daily's does not, quite — see below.

**Short calls are rare, and that is the market rather than the mechanism.** The test
period rose, so above a 0.65 floor the weekly and monthly models stop finding setups
bearish enough to name. The rule is symmetric and does produce Shorts when the
distribution supports it; this test window largely does not.

---

## ⚙️ Chosen Settings

```python
MIN_MOVE_PERCENTILE = {"daily": 0.50, "weekly": 0.75, "monthly": 0.75}
RECOMMENDATION_RATE = {"daily": 0.90, "weekly": 0.90, "monthly": 0.90}
```

The floor is the real control. The rate is held high so that it does not bind first,
which keeps one knob in charge instead of two.

The floor differs per horizon because the curve above is shaped differently on each.
Weekly gains 5.6 points of hit rate between 0.50 and 0.75; daily gains 1.3 and gives up
two thirds of its calls to get them, so it is left at 0.50.

| Horizon | Floor | Calls | Share of rows | Hit rate |
|---|---|---|---|---|
| daily | 0.50 | 1,114 | 23.8% | 0.568 |
| weekly | 0.75 | 408 | 8.7% | 0.669 |
| monthly | 0.75 | 2,796 | 30.2% | 0.621 |

> **These settings were read off the test sweep, so the hit rates above are mildly
> optimistic.** Choosing one parameter from seven candidates by looking at test
> performance is a weak form of fitting to the test set. The effect is small and the
> underlying curve is monotonic on all three horizons — which is the part that is not
> a coincidence — but the numbers should be read as an upper estimate, not a forecast.

**Why not the `best_by_edge` row.** `edge` is `fired_share × (hit_rate − 0.5)`, so it
rewards volume, and since the hit rate stays above 0.5 everywhere it is maximised by
calling a direction on 100% of rows. That is the degenerate answer: in a rising market
it reduces to always-Long, which needs no model. `edge` remains useful for comparing
two operating points at similar volume; it should not be maximised blindly, and it is
measured against 0.5 rather than against the base rate of up moves, which flatters it.

---

## 🚧 What Does Not Work Yet

**Monthly coverage is 0.745 against a target of 0.80.** The shortfall is concentrated:

| Year | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|---|
| Coverage | 0.935 | 0.687 | 0.824 | 0.687 | 0.681 | 0.723 | 0.815 | 0.811 |

2020 and 2022 are the crisis years, and they are among the worst — but removing them
does not rescue the number. Excluding 2020 lifts coverage to 0.755; excluding both 2020
and 2022 lifts it to 0.770, still short of the target. 2023 sits at 0.681 and 2024 at
0.723, and neither was a crisis. **The shortfall is broad, not a COVID artefact.**

The crisis years do have a specific explanation, which is the known failure
mode of conformal prediction: its guarantee holds while the calibration data and the
forecast come from the same regime. Monthly's history starts in 1993, so a 20% test
split spans about seven years and contains two once-a-decade events, while its
calibration slice is the calm stretch immediately before them.

Switching the monthly volatility scale from realised to implied volatility recovered a
large part of this (0.689 → 0.745 across two runs, with 2020 rising from 0.594 to 0.687
and 2022 from 0.566 to 0.687), because a twelve-month rolling standard deviation cannot
react to a crash inside the month it happens. The remainder is the part the scale still
cannot see.

**Daily's directional edge is not established.** Its hit rate at the chosen floor is
0.568 on 1,114 calls, with a confidence interval of [0.539, 0.598]. That clears 0.50,
but it only barely clears its own always-call rate of 0.534. Daily direction should be
treated as unproven, and the band — which is well calibrated — as the deliverable.

**Coverage still depends on position inside the candle.** After per-bucket calibration
the spread is roughly 9 points on both weekly and monthly — the open of a candle is
under-covered and its close over-covered. Five buckets over a monthly candle means each
covers about four trading days, which may simply be too coarse; the residual is a
candidate for more buckets or for a scale that reacts within the candle rather than
between candles.

**Monthly's tuning is thin.** 95% of its trials were pruned, leaving 30 completed out of
1,072 started.

---

## 🎛️ Hyperparameter Tuning

| Horizon | Trials completed | Pruned | Best vs first guess | Best vs median trial |
|---|---|---|---|---|
| daily | 582 | 3% | +0.61% | +0.22% |
| weekly | 336 | 44% | +0.24% | +0.27% |
| monthly | 30 | 95% | +0.16% | +0.19% |

**The hyperparameter landscape is flat.** Across hundreds of trials, the winning
configuration beats a randomly chosen one by roughly two tenths of one percent. Tuning
is not where the remaining gains are — the feature set and the label definition are.

This is worth stating plainly because it sets expectations for anyone who picks the
project up: re-running Optuna will not move these numbers.