# ⚙️ Backend — Data, API, and the AI Bridge

The backend has three jobs: **keep market data current**, **serve forecasts over HTTP**, and **be the single doorway between the GUI and the AI**.

> System overview: [`../../README.md`](../../README.md) · AI internals: [`../../ai/docs/README.md`](../../ai/docs/README.md)

---

## 📑 Table of Contents

- [Two Processes](#-two-processes)
- [REST API](#-rest-api)
- [The AI Bridge](#-the-ai-bridge)
- [Data Store](#-data-store)
- [Sync Logic](#-sync-logic)
- [Configuration](#-configuration)
- [Directory Map](#-directory-map)
- [Invariants](#-invariants)

---

## 🔀 Two Processes

`bootstrap.py` at the repo root launches both, then blocks on the API.

### `sync_main.py` — the 24/7 service

```
sync (blocking)  →  refresh_model (background thread)  →  scheduler (main thread, forever)
```

1. **Sync.** For each ticker, compare the newest stored candle against yfinance. Current → no download.
2. **Refresh.** Call `train_service.train_if_needed()` on a **daemon thread** and return immediately. The main loop never blocks on training.
3. **Schedule.** `sync_scheduler` runs on the **main thread**, sleeping one hour between checks and repeating forever.

> ⚠️ The scheduler occupies the main thread by design. Were `main()` to return, the interpreter would exit and take every daemon thread with it — including the one that is training.

`refresh_model()` is called on **every** cycle, not only when tickers were out of date. A machine with current data but no models would otherwise never build them, and would report `training` indefinitely.

### `rest_main.py` — the API

A FastAPI app under uvicorn. It comes up immediately, even while the first training run is still going, and reports honest status instead of stale numbers.

---

## 🌐 REST API

The full endpoint list, with parameters and examples, is in [`RESTAPI.md`](./RESTAPI.md). The forecast endpoint is the one the AI bridge serves:

| Method | Path | Query | Returns |
|---|---|---|---|
| `GET` | `/api/predictions/{symbol}` | `horizon=daily\|weekly\|monthly` | One forecast |

Every endpoint short-circuits while a data sync is running:

```json
{ "status": "error", "message": "Syncing is in progress. Please try again later." }
```

Otherwise the shape is **always the same**, so the client only ever reads `status`:

```jsonc
// still training
{ "status": "training", "message": "Models are updating...", "band": null }

// ready
{ "status": "ready", "message": null, "band": {
    "ticker": "SPY", "horizon": "daily", "based_on_date": "2026-07-08",
    "low_pct": -0.86, "mid_pct": 0.07, "high_pct": 0.90,
    "low_price": 744.80, "mid_price": 751.84, "high_price": 758.05,
    "anchor_price": 751.28,
    "stability": 0.67, "recommendation": "Stay-out"
} }
```

**Client loop:** request → if `status == "training"`, show a please-wait screen and retry in a few seconds → otherwise render the band. The client never talks to the AI and never checks readiness itself.

> The supporting series (`^VIX`, `^TNX`, `^IRX`, `DX-Y.NYB`) and the currency pairs are stored and served like any other symbol, but they are feature sources — they are never forecast, so they are absent from the prediction endpoint's ticker list.

---

## 🌉 The AI Bridge

Everything AI-facing lives in [`../ai_bridge/`](../ai_bridge/). Each module loads its AI counterpart **by file path**, because the AI stage folders are not importable packages — and because `ai/utils` and `backend/utils` would otherwise collide on the import path.

| Module | Public surface | Notes |
|---|---|---|
| [`forecast_service.py`](../ai_bridge/forecast_service.py) | `get_forecast(ticker, horizon)` | Checks readiness **before** building anything, so a stale model is never served |
| [`train_service.py`](../ai_bridge/train_service.py) | `train_if_needed()` | Owns the decision of what to run |
| [`model_status_service.py`](../ai_bridge/model_status_service.py) | `is_ready()`, `full_status()` | Read-only, cheap, safe to poll |

### What `train_if_needed()` decides

| Situation | Status | Action |
|---|---|---|
| No inference models (fresh clone) | `bootstrapped` | Runs `ai/runners/run_pipeline.py` once |
| A new candle closed | `trained` | Rebuilds only the affected horizon(s) |
| Everything current | `fresh` | Nothing |
| Another refresh running | `busy` | Nothing |

A file lock at `ai/runners/.routine.lock` prevents overlapping retrains. A lock older than **7 minutes** is treated as stale and cleared, so an interrupted run cannot wedge the system permanently.

The bridge also converts percent to price, anchored on the last close:

```python
low_price = anchor * (1 + low_pct / 100.0)
```

Percent points, hence `/100`; a multiplier, hence `1 +`. A `low_pct` of `-0.95` yields `anchor × 0.9905` — slightly below the anchor, as it should.

---

## 🗄️ Data Store

SQLite at `backend/database.db`. **Three tables per ticker**, one per horizon, each keyed on `date`.

| Component | Role |
|---|---|
| [`storage/TickerDB.py`](../storage/TickerDB.py) | One ticker's three tables; `add_dataframe` **appends** |
| [`storage/TickersDBManager.py`](../storage/TickersDBManager.py) | Owns the connection, hands out per-ticker handles |
| [`eod_data/Ticker_EOD_Manager.py`](../eod_data/Ticker_EOD_Manager.py) | Fetches from yfinance, computes indicators |
| [`eod_data/Ticker_EOD_Extractor.py`](../eod_data/Ticker_EOD_Extractor.py) | Turns raw OHLCV into stored indicator rows |
| [`eod_data/Ticker_EOD.py`](../eod_data/Ticker_EOD.py) | The row model |

History is fetched from **1990** — deep enough for the AI's monthly model to see real crashes.

Indicators and periods are documented in [`FEATURES.md`](./FEATURES.md). Periods are `[20, 50, 100, 150, 200]` and **must stay in step with `ai/config.py`'s `MA_PERIODS`**; a mismatch makes the AI silently skip features it expected.

### The partial-candle guard

```python
yf_latest = tickers_status[ticker]["yf_latest"]   # SyncManager's last CLOSED session
ticker_df = ticker_df[ticker_df.index <= yf_latest]
```

Mid-session, yfinance's daily download includes *today's unfinished candle*. [`SyncManager.last_finished_session()`](../sync/SyncManager.py) reads the trailing 10 days that `download_recent` fetched in bulk and returns the newest session that has actually closed, judged against the ticker's own exchange clock rather than a wall-clock date, which is what keeps weekends, holidays and pre-market fetches from confusing it. [`Tickers_EOD_Manager`](../eod_data/Ticker_EOD_Manager.py) then trims every ticker to that date before extraction. Because all three horizons are derived from the same trimmed daily rows, one guard at the daily level protects every horizon.

---

## 🔄 Sync Logic

| Component | Role |
|---|---|
| [`sync/SyncManager.py`](../sync/SyncManager.py) | Compares each ticker's stored date against yfinance |
| [`sync/SyncStatus.py`](../sync/SyncStatus.py) | Writes `backend/sync_status.json` |

`SyncStatus` is **file-based on purpose**. `sync_main` and `rest_main` are separate processes; an in-memory flag would be invisible across that boundary. A file is not.

Every ticker is checked **independently**, which matters: Tel Aviv closes hours before Wall Street, so on any given evening TA35 may have a fresh candle while SPY does not.

---

## ⚙️ Configuration

All of it in [`../config.json`](../config.json):

```jsonc
{
  "prediction_settings": {
    "tickers": ["SPY", "QQQ", "TA35.TA", "^TA125.TA", "^GDAXI", "^DJI"],
    "supporting_tickers": ["^VIX", "^TNX", "^IRX", "DX-Y.NYB"],
    "currencies": ["USDILS=X", "EURILS=X", "USDEUR=X", "EURUSD=X"],
    "horizons": ["daily", "weekly", "monthly"],
    "periods": [20, 50, 100, 150, 200],
    "db_name": "backend/database.db"
  },
  "rest_api_settings": { "host": "127.0.0.1", "port": 8000 }
}
```

> 🚨 **`db_name` must use forward slashes.** On Linux a backslash is a literal filename character: `"backend\\database.db"` creates a single oddly-named file in the repo root, while the AI looks for `backend/database.db` and finds nothing. Forward slashes work on both platforms — `pathlib` and `sqlite3` normalize them.

Loaded through [`utils/ConfigLoader.py`](../utils/ConfigLoader.py), which resolves the DB path relative to the repo root so the working directory never matters.

---

## 🗂️ Directory Map

| Path | Contents |
|---|---|
| `sync_main.py` | The 24/7 sync + train + schedule service |
| `rest_main.py` | FastAPI app |
| `ai_bridge/` | The only doorway to the AI |
| `eod_data/` | yfinance fetching and indicator computation |
| `storage/` | SQLite access |
| `sync/` | Freshness comparison and cross-process status |
| `utils/` | `ConsoleLogger`, `ConfigLoader`, `Banner` |
| `docs/` | This file, [`FEATURES.md`](./FEATURES.md) and [`RESTAPI.md`](./RESTAPI.md) |
| `database.db` 🚫 | Generated |
| `sync_status.json` 🚫 | Generated |

`ConsoleLogger` is shared: the AI imports it by file path through `ai/utils/log.py`, so both halves log with the same colors, timestamps, and level prefixes.

---

## 🧷 Invariants

Rules the backend depends on. Breaking one produces silent, hard-to-trace corruption.

- **`if_exists="append"`, never `"replace"`.** Replace wipes every historical row on an incremental sync.
- **The store can be *ahead* of yfinance.** After local midnight, the newest stored candle may be newer than the last candle yfinance reports as closed. A strict date-equality check treats that as "unsynced" and re-fetches; the download brings nothing new, so the store stays correct.
- **`refresh_model()` runs on every cycle.** Skipping it when data happens to be current leaves a model-less machine stuck.
- **`metadata.json` is written last.** If it exists, the boosters beside it are complete — which is exactly why `train_service` uses it as the "do models exist?" sentinel.
- **Periods must match `ai/config.py`.** The AI expects `sma_20`, `sma_50`, … by name.
- **Column names are a contract.** The AI reads every indicator by name, including the exogenous series stored as `^VIX_daily_last`, `^TNX_weekly_last` and so on. Renaming one does not raise anything on either side — it removes a feature from the model. `ai/config.py`'s `SUPPORT_SERIES_PREFIX` is the translation table, and `extract_dataset.validate_pooled` warns when an expected column stops arriving.