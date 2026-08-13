# 📈 AlgoTrade

A local, end-of-day **index forecasting engine**. It predicts an **80% confidence band** for the next candle of six major indices across three horizons, and turns that band into a Long / Short / Stay-out call.

Nothing is live-traded. Nothing leaves the machine. The system syncs market data once a day, retrains only what a newly closed candle requires, and serves forecasts over a local REST API.

---

## 📑 Table of Contents

- [What It Predicts](#-what-it-predicts)
- [Quick Start](#-quick-start)
- [How It Fits Together](#-how-it-fits-together)
- [Repository Layout](#-repository-layout)
- [Lifecycle](#-lifecycle)
- [Development Workflows](#-development-workflows)
- [Generated Artifacts](#-generated-artifacts)
- [Team & Ownership](#-team--ownership)

---

## 🎯 What It Predicts

For every (ticker, horizon) pair the engine returns a band, not a point:

| Field | Meaning |
|---|---|
| `low_pct` / `high_pct` | The 80% band edges, in percent points (Q10 and Q90) |
| `mid_pct` | The median forecast (Q50) — where the model leans inside the band |
| `low_price` / `mid_price` / `high_price` | The same band converted to prices |
| `anchor_price` | The last close the percentages were applied to |
| `stability` | 0–1: how narrow today's band is versus this horizon's history. **Not** the 80% level |
| `prob_up` | 0–1: P(next move > 0), read off the three fitted quantiles |
| `recommendation` | `Long`, `Short`, or `Stay-out`, from where `prob_up` ranks against this horizon's own history |
| `based_on_date` | The last closed candle the forecast rests on |

**Tickers:** SPY, QQQ, TA35, TA125, DAX, DJI. *(VIX, the Treasury yields and the dollar index are fetched as feature sources only — they are never forecast.)*

**Horizons:** `daily`, `weekly`, `monthly`.

> The band always promises 80% coverage. `stability` tells you whether that promise arrived on a narrow band (calm market) or a wide one (turbulent market).

---

## 🚀 Quick Start

```bash
# 1. Python environment
pip install -r requirements.txt

# 2. Bring the whole system up
python bootstrap.py
```

On a fresh machine `bootstrap.py` syncs history back to 1990, builds all nine models from scratch (~2 minutes), and starts the REST API. On later launches it goes straight to serving.

The front end is a separate Node project:

```bash
cd gui && npm install && npm run dev
```

**Requirements:** Python 3.11+, and Node 18+ for the front end.

---

## 🧩 How It Fits Together

```
┌──────────┐   HTTP    ┌───────────────┐   function call   ┌──────────────┐
│   GUI    │ ────────► │    Backend    │ ────────────────► │      AI      │
│ (React)  │ ◄──────── │   (FastAPI)   │ ◄──────────────── │  (LightGBM)  │
└──────────┘  band or  └───────┬───────┘   band or status  └──────┬───────┘
              "training"       │                                  │
                               │ yfinance                         │ reads
                               ▼                                  ▼
                        ┌─────────────┐                   ┌──────────────┐
                        │ database.db │ ─────────────────►│  data_store  │
                        │  (SQLite)   │                   │  (parquet)   │
                        └─────────────┘                   └──────────────┘
```

The GUI never touches the AI directly. Everything crosses the boundary through **`backend/ai_bridge/`**, the single place the two halves meet.

| Bridge module | Purpose |
|---|---|
| [`forecast_service.py`](backend/ai_bridge/forecast_service.py) | `get_forecast(ticker, horizon)` — guards on readiness, then returns a band |
| [`train_service.py`](backend/ai_bridge/train_service.py) | `train_if_needed()` — decides whether to build everything, retrain one horizon, or do nothing |
| [`model_status_service.py`](backend/ai_bridge/model_status_service.py) | `is_ready()` / `full_status()` — read-only freshness check |

---

## 📂 Repository Layout

| Path | Owner | What lives there |
|---|---|---|
| [`ai/`](ai/docs/README.md) | Lidor | Feature engineering, training, tuning, inference |
| [`backend/`](backend/docs/README.md) | Eran | Market-data sync, SQLite store, REST API, AI bridge |
| [`gui/`](gui/README.md) | Liel | React + Vite front end |
| `bootstrap.py` | — | Single entry point: starts the sync service and the REST API |
| `requirements.txt` | — | Python dependencies for `ai/` and `backend/` |

Feature definitions are documented **separately per side**, because the two sides compute different things:

- [`ai/docs/FEATURES.md`](ai/docs/FEATURES.md) — the model's engineered features
- [`ai/docs/RESULTS.md`](ai/docs/RESULTS.md) — how the current model measures up
- [`backend/docs/FEATURES.md`](backend/docs/FEATURES.md) — the indicators the backend stores

The REST surface is listed in [`backend/docs/RESTAPI.md`](backend/docs/RESTAPI.md).

---

## 🔄 Lifecycle

`bootstrap.py` launches two processes and then blocks on the API.

### 1. `backend/sync_main.py` — the 24/7 service

1. **Sync (blocking, fast).** Compares each ticker's latest stored candle against yfinance. Already current → no download.
2. **Refresh (background).** Hands off to `train_service.train_if_needed()` on a daemon thread and returns immediately, so nothing blocks.
3. **Schedule (main thread).** Sleeps until the configured `sync_time` and repeats forever.

> ⚠️ The scheduler occupies the **main** thread by design. Were `main()` to return, the interpreter would exit and take every daemon thread with it — including the one that is training.

### 2. `backend/rest_main.py` — the API

Comes up immediately, even while models are still training. A forecast request during training returns `{"status": "training"}` rather than a stale answer.

### What `train_if_needed()` decides

| Situation | Status returned | Action |
|---|---|---|
| No models on disk (fresh clone) | `bootstrapped` | Runs the full pipeline once |
| A new candle closed | `trained` | Retrains only the affected horizon(s) |
| Everything current | `fresh` | Nothing |
| Another refresh in progress | `busy` | Nothing |

Readiness is a **date comparison** — the model's `last_trained_through` against the newest candle — never a stored boolean, so it cannot go stale.

---

## 🛠️ Development Workflows

```bash
# Full AI pipeline: train, evaluate, report, rebuild production models
python ai/runners/run_pipeline.py

# Bring the whole system up (sync + train-if-needed + REST API)
python bootstrap.py

# Force the GPU for LightGBM (CPU is faster at this data scale)
ALGOTRADE_LGBM_DEVICE=gpu python ai/runners/run_pipeline.py
```

Hyperparameter tuning runs on the BGU SLURM cluster — see [`ai/docs/README.md`](ai/docs/README.md#-hyperparameter-tuning).

---

## 🗃️ Generated Artifacts

Rebuilt by the code, kept out of version control:

| Path | Contents |
|---|---|
| `backend/database.db` | Synced OHLCV + indicators, one table per ticker per horizon |
| `backend/sync_status.json` | Runtime sync flag, read across processes |
| `ai/data_store/` | Intermediate parquet: raw → features → splits |
| `ai/dev_models/` | Boosters from the evaluation run |
| `ai/Inference_models/` | The production boosters actually served |
| `ai/results/` | Metrics, plots, reports |
| `ai/tuning/studies/` | Optuna SQLite studies (per-machine) |

`ai/tuning/best_params/*.json` **is** committed, so the whole team gets the tuned model without re-running Optuna.

---

## 👥 Team & Ownership

| Area | Owner | Entry point |
|---|---|---|
| AI / modeling | **Lidor** | [`ai/docs/README.md`](ai/docs/README.md) · [`RESULTS.md`](ai/docs/RESULTS.md) |
| Backend / data | **Eran** | [`backend/docs/README.md`](backend/docs/README.md) |
| GUI / front end | **Liel** | [`gui/README.md`](gui/README.md) |

Course project — *AlgoTrade*, Ben-Gurion University.