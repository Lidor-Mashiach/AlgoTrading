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

# 2. Run it
python main.py
```

`main.py` is the entry point. It starts the backend, serves the front end and opens a dedicated window on it. Closing that window stops everything.

On a fresh machine the first run syncs history back to 1990 and builds all nine models before a forecast can be served. The interface opens as soon as the database is populated, and waits for the rest on its own.

**Requirements:** Python 3.11+. Nothing else.

> Node is **not** needed to run the system. The built front end is committed under `gui/dist/` and served by `gui/serve.py` using the standard library alone. Node is only needed to change the front end, and `main.py` switches to the Vite dev server by itself when `gui/node_modules` is present.

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
| [`gui/`](gui/README.md) | Lidor | Single page front end, React and Vite |
| `main.py` | — | Entry point: starts the backend, serves the GUI, opens the window |
| `bootstrap.py` | — | Starts the sync service and the REST API. Called by `main.py` |
| `requirements.txt` | — | Python dependencies for `ai/` and `backend/` |

Feature definitions are documented **separately per side**, because the two sides compute different things:

- [`ai/docs/FEATURES.md`](ai/docs/FEATURES.md) — the model's engineered features
- [`ai/docs/RESULTS.md`](ai/docs/RESULTS.md) — how the current model measures up
- [`backend/docs/FEATURES.md`](backend/docs/FEATURES.md) — the indicators the backend stores

The REST surface is listed in [`backend/docs/RESTAPI.md`](backend/docs/RESTAPI.md).

---

## 🔄 Lifecycle

`main.py` starts `bootstrap.py`, waits for the front end to answer, then opens the window and blocks until it closes. `bootstrap.py` itself launches two processes.

### 1. `backend/sync_main.py` — the 24/7 service

1. **Sync (blocking, fast).** Compares each ticker's latest stored candle against yfinance. Already current → no download.
2. **Refresh (background).** Hands off to `train_service.train_if_needed()` on a daemon thread and returns immediately, so nothing blocks.
3. **Schedule (main thread).** Sleeps one hour, then repeats forever.

> ⚠️ The scheduler occupies the **main** thread by design. Were `main()` to return, the interpreter would exit and take every daemon thread with it — including the one that is training.

### 2. `backend/rest_main.py` — the API

Comes up immediately, even while models are still training. A forecast request during training returns `{"status": "training"}` rather than a stale answer.

### 3. `gui/serve.py` or the Vite dev server — the front end

Serves the interface on port 5173 and forwards `/api` to the REST API, so the page and its data share one origin and no cross origin request is ever made. `main.py` picks the Vite dev server when `gui/node_modules` exists, and `gui/serve.py` otherwise.

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

# Front end: install once, then develop with hot reload
cd gui && npm install && npm run dev

# Front end: rebuild the committed output after changing src/
cd gui && npm run build
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
| `gui/node_modules/` | Front end dependencies, restored by `npm install` |

`ai/tuning/best_params/*.json` **is** committed, so the whole team gets the tuned model without re-running Optuna.

`gui/dist/` **is** committed for the same reason: it is what lets the system run on a machine with no Node installed. Rebuild it with `npm run build` inside `gui/` after changing the front end, and commit the result.

---

## 👥 Team & Ownership

| Area | Owner | Entry point |
|---|---|---|
| AI / modeling | **Lidor** | [`ai/docs/README.md`](ai/docs/README.md) · [`RESULTS.md`](ai/docs/RESULTS.md) |
| Backend / data | **Eran** | [`backend/docs/README.md`](backend/docs/README.md) |
| GUI / front end | **Lidor** | [`gui/README.md`](gui/README.md) |

Course project — *AlgoTrade*, Ben-Gurion University.