# 🧬 Feature catalog (AI model facing)

This document lists the features the models actually consume, after feature engineering.
It complements the raw data catalog owned by the backend. The raw catalog describes what
the data layer produces. This catalog describes what enters the boosters.

Everything here is produced inside `1_PreTraining/Feature-Eng/build_features.py` and stored
per horizon in the intermediate data store. The exact indicator conventions live in the
main `README.md`.

| Horizon | Columns the booster sees |
| --- | --- |
| daily | 46 |
| weekly | 42 |
| monthly | 38 |

---

## 🧭 Conventions

- **One label, three quantiles.** Each horizon has a single real label. The Q10, Q50, and
  Q90 boosters all train on the same features and the same label. Only the pinball alpha
  differs between them.
- **Anchor close.** The running daily close at each row's date is the universal anchor. It
  is the denominator of the label and the reference close in every relative feature, which
  keeps the engineering consistent with the intra-candle convention. The anchor is a helper
  column and is never fed to the model.
- **Scale.** Every percentage feature and the label are expressed in percentage points, for
  example a value of 1.5 means a move of one and a half percent.
- **No scaling.** LightGBM is scale invariant, so there is no z-score and no normalization.
  Raw numeric columns enter as they are.
- **Own price levels are excluded, exogenous levels are not.** A moving average, a Bollinger
  band, a MACD line and an ATR are all quoted in the ticker's own currency, so they drift
  with the price over decades and mean different things on different indices. Each is
  divided by the anchor before the model sees it. An implied-volatility level, a Treasury
  yield and a dollar index are exogenous to the ticker and range-bound over the sample, so
  they enter as levels and describe the regime the forecast is being made in.
- **Ticker is a feature.** The index identity enters as a native categorical feature, which
  lets one pooled model still specialize per index.
- **Missing values.** LightGBM handles missing values natively, so warm-up NaNs created by
  the long moving averages are kept and routed by the trees. Only rows without a realized
  label are dropped.

---

## 🌍 Exogenous series

The backend stores four market-wide series alongside every ticker's own indicators, named
after their yfinance symbol. The extraction adapter renames them to a canonical prefix on
the way in, so nothing downstream carries a caret or a dot in a column name.

| Backend column | Model column | Series |
| --- | --- | --- |
| `^VIX_{horizon}_last` | `vix_{horizon}_last` | Implied volatility of S&P options |
| `^TNX_{horizon}_last` | `tnx_{horizon}_last` | 10-year Treasury yield |
| `^IRX_{horizon}_last` | `irx_{horizon}_last` | 13-week Treasury yield |
| `DX-Y.NYB_{horizon}_last` | `dxy_{horizon}_last` | US dollar index |

The map lives in `config.SUPPORT_SERIES_PREFIX`. It is the only place the backend's symbol
spelling is allowed to matter, and `extract_dataset.py` warns when an expected column does
not arrive, so a rename on the data side cannot quietly remove a feature from the model.

Each series contributes twice. The **level** says which regime the market is in. The
**change between candles** says whether that regime is deteriorating, which is the part
that widens a band. Yields move in percentage points already, so their change is an
absolute difference; the index-like series use a percent change.

---

## 🎯 Label

| Horizon | Label column | Definition |
| --- | --- | --- |
| daily | `target_daily` | Percent move from the current daily close to the next day's close |
| weekly | `target_weekly` | Percent move from the row's anchor to the in-progress week's closing value |
| monthly | `target_monthly` | Percent move from the row's anchor to the in-progress month's closing value |

The label is the only place that looks forward. No feature uses any future information. Rows
of a candle that has not closed yet are dropped, because their label is not realized. The one
exception is a candle's closing row: its in-candle move is 0 by construction, so it is rolled
over to target the NEXT candle's close (days_to_close set to 1.0, grouped with that next
candle) - exactly how the daily horizon always works. This keeps a weekly and monthly
forecast available over weekends and month ends.

---

## 📅 Daily features

**Engineered**

| Feature | Built from | Meaning |
| --- | --- | --- |
| `dist_sma_daily_{20,50,100,150,200}` | anchor close and `sma_daily_{p}` | Percent distance of the close above or below each simple moving average |
| `dist_ema_daily_{20,50,100,150,200}` | anchor close and `ema_daily_{p}` | Percent distance of the close from each exponential moving average |
| `bb_pctb_daily` | anchor close and the daily Bollinger bands | Position of the close inside the band, zero at the lower band and one at the upper band |
| `bb_width_daily` | the daily Bollinger bands | Band width over its base, a volatility proxy |
| `rel_vol_daily` | `volume_prev_day` and `volume_avg_daily_90` | Recent volume relative to its ninety-day average |
| `range_pct_daily` | `high_prev_day`, `low_prev_day`, anchor close | Previous day's high to low range as a percent of the close |
| `macd_pct_daily` | `macd_daily` and anchor close | Distance between the fast and slow moving averages, as a percent of the close |
| `macd_hist_pct_daily` | `macd_daily`, `macd_signal_daily`, anchor close | The MACD histogram, as a percent of the close: momentum acceleration |
| `atr_pct_daily` | `atr_daily` and anchor close | Average true range as a percent of the close, the direct read on how far this index moves in a day |
| `atr_pct_weekly` | `atr_weekly` and anchor close | Running weekly true range as a percent of the close (cross-horizon context) |
| `atr_pct_monthly` | `atr_monthly` and anchor close | Running monthly true range as a percent of the close (cross-horizon context) |
| `stoch_gap_daily` | `stoch_k_daily` and `stoch_d_daily` | Stochastic %K minus %D, the crossing signal |
| `term_spread_daily` | `tnx_daily_last` and `irx_daily_last` | Ten-year yield minus thirteen-week yield, the shape of the curve |
| `vix_chg_daily` | `vix_daily_last` | Percent move of implied volatility since the previous candle |
| `dxy_chg_daily` | `dxy_daily_last` | Percent move of the dollar index since the previous candle |
| `tnx_chg_daily` | `tnx_daily_last` | Change in the ten-year yield since the previous candle, in yield points |
| `realized_vol_daily` | `pct_change_daily_last` | Rolling standard deviation of daily returns |
| `dow_sin`, `dow_cos` | the date | Cyclical encoding of the day of week |
| `days_to_close_weekly` | the date | Trading days left until the week closes, as a fraction (cross-horizon context) |
| `days_to_close_monthly` | the date | Trading days left until the month closes, as a fraction (cross-horizon context) |
| `month_sin`, `month_cos` | the date | Cyclical encoding of the month of year |

**Passthrough (raw, entered unchanged)**

| Feature | Meaning |
| --- | --- |
| `pct_change_daily_last` | Percent move of the last completed daily candle |
| `rsi_daily` | Relative strength index |
| `rsi_ma_daily` | Moving average of the relative strength index |
| `rsi_gap_daily` | Gap between the relative strength index and its moving average |
| `stoch_k_daily` | Stochastic %K, position inside the recent range |
| `stoch_d_daily` | Stochastic %D, the smoothed %K |
| `vix_daily_last` | Implied volatility level |
| `tnx_daily_last` | Ten-year Treasury yield |
| `irx_daily_last` | Thirteen-week Treasury yield |
| `dxy_daily_last` | Dollar index level |
| `pct_change_week_current` | Percent move of the week so far (cross-horizon context) |
| `pct_change_month_current` | Percent move of the month so far (cross-horizon context) |
| `vix_weekly_last` | Implied volatility on the weekly view (cross-horizon context) |
| `vix_monthly_last` | Implied volatility on the monthly view (cross-horizon context) |
| `ticker` | Index identity, a categorical feature |

---

## 🗓️ Weekly features

**Engineered**

| Feature | Built from | Meaning |
| --- | --- | --- |
| `dist_sma_weekly_{20,50,100,150,200}` | anchor close and `sma_weekly_{p}` | Percent distance of the running close from each weekly simple moving average |
| `dist_ema_weekly_{20,50,100,150,200}` | anchor close and `ema_weekly_{p}` | Percent distance from each weekly exponential moving average |
| `bb_pctb_weekly` | anchor close and the weekly Bollinger bands | Position of the close inside the weekly band |
| `bb_width_weekly` | the weekly Bollinger bands | Weekly band width over its base |
| `rel_vol_week_current` | `volume_week_current` and `volume_week_prev` | This week's volume relative to last week's |
| `range_pct_week_prev` | `high_week_prev`, `low_week_prev`, anchor close | Previous week's range as a percent of the close |
| `macd_pct_weekly` | `macd_weekly` and anchor close | Weekly MACD line as a percent of the close |
| `macd_hist_pct_weekly` | `macd_weekly`, `macd_signal_weekly`, anchor close | Weekly MACD histogram as a percent of the close |
| `atr_pct_weekly` | `atr_weekly` and anchor close | Weekly average true range as a percent of the close |
| `atr_pct_monthly` | `atr_monthly` and anchor close | Running monthly true range as a percent of the close (cross-horizon context) |
| `stoch_gap_weekly` | `stoch_k_weekly` and `stoch_d_weekly` | Weekly Stochastic %K minus %D |
| `term_spread_weekly` | `tnx_weekly_last` and `irx_weekly_last` | Ten-year yield minus thirteen-week yield on the weekly view |
| `vix_chg_weekly` | `vix_weekly_last` | Percent move of implied volatility between closed weeks |
| `dxy_chg_weekly` | `dxy_weekly_last` | Percent move of the dollar index between closed weeks |
| `tnx_chg_weekly` | `tnx_weekly_last` | Change in the ten-year yield between closed weeks, in yield points |
| `realized_vol_weekly` | `pct_change_week_prev` | Rolling standard deviation of weekly returns |
| `days_to_close_weekly` | the date | Trading days left until the week closes, as a fraction |
| `days_to_close_monthly` | the date | Trading days left until the month closes, as a fraction (cross-horizon context) |
| `month_sin`, `month_cos` | the date | Cyclical encoding of the month of year |

**Passthrough (raw, entered unchanged)**

| Feature | Meaning |
| --- | --- |
| `pct_change_week_current` | Percent move of the week so far |
| `pct_change_week_prev` | Percent move of the last completed week |
| `rsi_weekly` | Weekly relative strength index |
| `rsi_ma_weekly` | Moving average of the weekly relative strength index |
| `rsi_gap_weekly` | Gap between the weekly relative strength index and its moving average |
| `stoch_k_weekly` | Weekly Stochastic %K |
| `stoch_d_weekly` | Weekly Stochastic %D |
| `vix_weekly_last` | Implied volatility level on the weekly view |
| `tnx_weekly_last` | Ten-year Treasury yield on the weekly view |
| `irx_weekly_last` | Thirteen-week Treasury yield on the weekly view |
| `dxy_weekly_last` | Dollar index level on the weekly view |
| `pct_change_month_current` | Percent move of the month so far (cross-horizon context) |
| `vix_monthly_last` | Implied volatility on the monthly view (cross-horizon context) |
| `ticker` | Index identity, a categorical feature |

---

## 📆 Monthly features

**Engineered**

| Feature | Built from | Meaning |
| --- | --- | --- |
| `dist_sma_monthly_{20,50,100,150,200}` | anchor close and `sma_monthly_{p}` | Percent distance of the running close from each monthly simple moving average |
| `dist_ema_monthly_{20,50,100,150,200}` | anchor close and `ema_monthly_{p}` | Percent distance from each monthly exponential moving average |
| `bb_pctb_monthly` | anchor close and the monthly Bollinger bands | Position of the close inside the monthly band |
| `bb_width_monthly` | the monthly Bollinger bands | Monthly band width over its base |
| `rel_vol_month_current` | `volume_month_current` and `volume_month_prev` | This month's volume relative to last month's |
| `range_pct_month_prev` | `high_month_prev`, `low_month_prev`, anchor close | Previous month's range as a percent of the close |
| `macd_pct_monthly` | `macd_monthly` and anchor close | Monthly MACD line as a percent of the close |
| `macd_hist_pct_monthly` | `macd_monthly`, `macd_signal_monthly`, anchor close | Monthly MACD histogram as a percent of the close |
| `atr_pct_monthly` | `atr_monthly` and anchor close | Monthly average true range as a percent of the close |
| `stoch_gap_monthly` | `stoch_k_monthly` and `stoch_d_monthly` | Monthly Stochastic %K minus %D |
| `term_spread_monthly` | `tnx_monthly_last` and `irx_monthly_last` | Ten-year yield minus thirteen-week yield on the monthly view |
| `vix_chg_monthly` | `vix_monthly_last` | Percent move of implied volatility between closed months |
| `dxy_chg_monthly` | `dxy_monthly_last` | Percent move of the dollar index between closed months |
| `tnx_chg_monthly` | `tnx_monthly_last` | Change in the ten-year yield between closed months, in yield points |
| `realized_vol_monthly` | `pct_change_month_prev` | Rolling standard deviation of monthly returns |
| `days_to_close_monthly` | the date | Trading days left until the month closes, as a fraction |
| `month_sin`, `month_cos` | the date | Cyclical encoding of the month of year |

**Passthrough (raw, entered unchanged)**

| Feature | Meaning |
| --- | --- |
| `pct_change_month_current` | Percent move of the month so far |
| `pct_change_month_prev` | Percent move of the last completed month |
| `rsi_monthly` | Monthly relative strength index |
| `rsi_ma_monthly` | Moving average of the monthly relative strength index |
| `rsi_gap_monthly` | Gap between the monthly relative strength index and its moving average |
| `stoch_k_monthly` | Monthly Stochastic %K |
| `stoch_d_monthly` | Monthly Stochastic %D |
| `vix_monthly_last` | Implied volatility level on the monthly view |
| `tnx_monthly_last` | Ten-year Treasury yield on the monthly view |
| `irx_monthly_last` | Thirteen-week Treasury yield on the monthly view |
| `dxy_monthly_last` | Dollar index level on the monthly view |
| `ticker` | Index identity, a categorical feature |

---

## 🧮 How the intra-candle rows are used

Every horizon is built from the same daily rows. A weekly row dated Wednesday carries the
week's running state: the volume accumulated so far, the running high and low, the running
Bollinger window, the running ATR. That is what lets the weekly model answer "where does
this week close" on a Wednesday and not only on a Friday.

Two consequences follow, and both are handled in `utils/features.py`:

- A column that describes a **closed** candle (`pct_change_week_prev`, `vix_weekly_last`)
  repeats its value on every intra-candle row. Any window over such a column has to run on
  one value per candle and be mapped back, otherwise the same candle is counted five or
  twenty-one times. `per_candle_transform` does that, and both `realized_vol_*` and every
  `*_chg_*` feature go through it.
- A column that describes the **running** candle (`atr_weekly`, `bb_base_monthly`) changes
  on every intra-candle row and is used as it is.

---

## 🚫 Columns the model never sees

These are present in the raw tables but are dropped before training. Raw price levels are
non-stationary, so the model uses relative features built from them instead.

- **Raw price levels.** `close_{daily,weekly,monthly}_last`, every `sma_*` and `ema_*`, the
  Bollinger base, upper, and lower bands, the raw high, low, and volume columns, and the
  price-unit form of `macd_*`, `macd_signal_*` and `atr_*`.
- **Helpers.** The anchor close and the candle period identifier, used only to build the
  label and the group-aware split.

---

## 🗒️ Notes

- Features are only created when their raw inputs are present. On partial data, a feature
  with a missing input is skipped and reported, so the pipeline still runs end to end.
- `days_to_close` uses a business-day approximation that ignores market holidays until a
  real trading calendar is wired into the data layer.