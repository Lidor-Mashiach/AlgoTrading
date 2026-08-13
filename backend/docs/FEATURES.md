# 📊 Raw Feature Catalog

> **Single source of truth** for the raw EOD data the extractor produces (one row per `Date`,
> per ticker). These are the **raw columns** as they come out of the data layer, with the exact
> names used in the project. The AI module engineers model-ready features **from** these (see
> [`../../ai/docs/README.md`](../../ai/docs/README.md) for which raw columns enter the model directly, which are
> transformed, and which are dropped).

All values are end-of-day (EOD). "Current week" and "current month" mean the still-open candle,
measured up to the last closed daily candle. Column names below match the extractor output
exactly.

---

## 0. Index

| Column | Meaning |
|--------|---------|
| `Date` | trading date of the row |
| `ticker` | which index the row belongs to (**add when pooling multiple indices**) |

## 1. Close and Returns

> All `pct_change_*` are in **percentage points** (already times 100, for example `-1.89` means
> minus 1.89 percent). `close_*_last` for weekly and monthly is the **last closed** week or month
> close (lagged).

| Column | Meaning | Horizon |
|--------|---------|---------|
| `close_daily_last` | last daily close (price) | daily |
| `close_weekly_last` | last closed weekly close (price) | weekly |
| `close_monthly_last` | last closed monthly close (price) | monthly |
| `pct_change_daily_last` | percent move of last daily candle | daily |
| `pct_change_week_current` | percent move of the open week so far | weekly |
| `pct_change_week_prev` | percent move of the last closed week | weekly |
| `pct_change_month_current` | percent move of the open month so far | monthly |
| `pct_change_month_prev` | percent move of the last closed month | monthly |

## 2. Simple Moving Averages (SMA)

Periods **20, 50, 100, 150, 200** for each horizon.

| Column pattern | Meaning |
|----------------|---------|
| `sma_daily_{20,50,100,150,200}` | daily SMAs (price) |
| `sma_weekly_{20,50,100,150,200}` | weekly SMAs (price) |
| `sma_monthly_{20,50,100,150,200}` | monthly SMAs (price) |

## 3. Exponential Moving Averages (EMA)

Periods **20, 50, 100, 150, 200** for each horizon.

| Column pattern | Meaning |
|----------------|---------|
| `ema_daily_{20,50,100,150,200}` | daily EMAs (price) |
| `ema_weekly_{20,50,100,150,200}` | weekly EMAs (price) |
| `ema_monthly_{20,50,100,150,200}` | monthly EMAs (price) |

## 4. Volume

| Column | Meaning |
|--------|---------|
| `volume_prev_day` | previous day's volume |
| `volume_avg_daily_90` | average daily volume over about 90 trading days |
| `volume_week_current` | volume of the open week |
| `volume_week_prev` | volume of the last closed week |
| `volume_month_current` | volume of the open month |
| `volume_month_prev` | volume of the last closed month |

## 5. Range (Low and High)

| Column | Meaning |
|--------|---------|
| `low_prev_day` and `high_prev_day` | previous daily candle low and high |
| `low_week_current` and `high_week_current` | open weekly candle low and high |
| `low_week_prev` and `high_week_prev` | last closed weekly candle low and high |
| `low_month_current` and `high_month_current` | open monthly candle low and high |
| `low_month_prev` and `high_month_prev` | last closed monthly candle low and high |

## 6. Bollinger Bands

> Parameters from the extractor. Period **20**, **k of 2 sigma**, population std (ddof of 0).
> `bb_base` is the 20-period SMA. Weekly and monthly fold the current running candle into the
> window.

| Column | Meaning |
|--------|---------|
| `bb_base_daily`, `bb_upper_daily`, `bb_lower_daily` | daily band center (SMA-20), upper, lower (price) |
| `bb_base_weekly`, `bb_upper_weekly`, `bb_lower_weekly` | weekly band center, upper, lower |
| `bb_base_monthly`, `bb_upper_monthly`, `bb_lower_monthly` | monthly band center, upper, lower |

## 7. RSI (with its moving average and gap)

> Parameters from the extractor. **Wilder's RSI, length 14**. `rsi_ma` is a simple 14-period MA of
> the RSI (TradingView default). Weekly and monthly include the current running candle's RSI.

| Column | Meaning |
|--------|---------|
| `rsi_daily`, `rsi_weekly`, `rsi_monthly` | Wilder RSI(14), 0 to 100, per horizon |
| `rsi_ma_daily`, `rsi_ma_weekly`, `rsi_ma_monthly` | SMA-14 of the RSI |
| `rsi_gap_daily`, `rsi_gap_weekly`, `rsi_gap_monthly` | RSI minus its MA (momentum acceleration) |

## 8. MACD

> Parameters from the extractor. Fast **12**, slow **26**, signal **9**, spans scaled per horizon.
> Weekly and monthly fold the running candle's close into the last closed candle's EMA. Values are
> in **price units**.

| Column | Meaning |
|--------|---------|
| `macd_daily`, `macd_weekly`, `macd_monthly` | fast EMA minus slow EMA, per horizon |
| `macd_signal_daily`, `macd_signal_weekly`, `macd_signal_monthly` | signal line (EMA-9 of the MACD) |

## 9. ATR

> Parameters from the extractor. **Wilder's ATR, length 14**. Weekly and monthly use the running
> candle's cumulative high and low against the last closed candle's close. Values are in
> **price units**.

| Column | Meaning |
|--------|---------|
| `atr_daily`, `atr_weekly`, `atr_monthly` | average true range per horizon |

## 10. Stochastic Oscillator

> Parameters from the extractor. Look-back **14**, %K smoothing **3**, %D smoothing **3**.
> Both series are bounded 0 to 100.

| Column | Meaning |
|--------|---------|
| `stoch_k_daily`, `stoch_k_weekly`, `stoch_k_monthly` | %K, position of the close inside the recent range |
| `stoch_d_daily`, `stoch_d_weekly`, `stoch_d_monthly` | %D, the smoothed %K |

## 11. Supporting series (market-wide gauges, features, not targets)

> One column per series per horizon, named after the yfinance symbol. Daily is the previous
> session's close (D minus 1); weekly and monthly are the last closed week's and month's close.

| Column pattern | Series |
|--------|---------|
| `^VIX_{daily,weekly,monthly}_last` | implied volatility of S&P options |
| `^TNX_{daily,weekly,monthly}_last` | 10-year Treasury yield |
| `^IRX_{daily,weekly,monthly}_last` | 13-week Treasury yield |
| `DX-Y.NYB_{daily,weekly,monthly}_last` | US dollar index |

---

## 🌐 Tracked Indices

| Display name | yfinance ticker | Notes |
|--------------|-----------------|-------|
| S&P 500 ETF | `SPY` | |
| Nasdaq 100 ETF | `QQQ` | |
| TA-35 | `TA35.TA` | TA-25 was renamed and expanded to TA-35 in 2017, one continuous series |
| TA-125 | `TA125.TA` | |
| DAX | `^GDAXI` | |
| Dow Jones | `^DJI` | |
| VIX | `^VIX` | feature only, not a target |
| 10-year Treasury yield | `^TNX` | feature only, not a target |
| 13-week Treasury yield | `^IRX` | feature only, not a target |
| US dollar index | `DX-Y.NYB` | feature only, not a target |

> Prediction targets (per horizon, `target_daily`, `target_weekly`, `target_monthly`) are the
> **percent move of the next or current candle's close** vs. the last daily close. They are
> **constructed in the AI module**, not part of the raw extract. See
> [`../../ai/docs/README.md`](../../ai/docs/README.md).