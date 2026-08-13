# 🚀 Inference_models

This folder builds the models that ship and provides the runtime entry point the backend and
GUI call. It takes the splits produced by PreTraining, refits on all of the data, and saves
the deployable boosters with their metadata.

Run it with `run_final_training.py`, which builds the models and then runs a smoke test.

---

## 🧱 What it produces

| File | Role |
| --- | --- |
| `build_final_models.py` | Refits the three quantile boosters per horizon on all data and saves them with metadata |
| `predictor.py` | The runtime entry point, returns a band and a stability score from a feature row |
| `verify_inference.py` | A smoke test that loads the models and runs a dummy prediction |

---

## 🔁 Build on all data

The development models in `../2_Train` are trained on the train split so they can be judged on
an untouched test split. The deployable models are different. Once the evaluation is trusted,
there is no reason to hold data back, so this stage unifies the train and test splits and
refits on the full dataset. It reuses the number of boosting rounds chosen during
development cross-validation, scaled up for the larger row count.

This is a **full retrain**. There is no continued training. When new data arrives, this stage
runs again from scratch. The metadata records `last_trained_through` per horizon so it is
always clear how current a model is.

---

## 🔮 The prediction contract

`predictor.py` exposes two stable functions:

```python
predict(ticker: str, horizon: str, features: dict) -> {
    "low": Q10, "mid": Q50, "high": Q90,
    "stability": float, "prob_up": float, "recommendation": str
}

predict_latest(ticker: str, horizon: str) -> same dict plus "based_on_date"
```

- `low` and `high` are the band edges in percentage points and `mid` is the median.
- `stability` is a value between zero and one that rises as the band tightens relative to
  this horizon's own history. It is not the 80% level, which is fixed.
- `prob_up` is P(next move > 0), read off the three quantiles as points on the outcome's
  cumulative distribution.
- `recommendation` is `Long`, `Short`, or `Stay-out`, decided by ranking `prob_up`
  against cut points stored in the metadata.
- The band edges are sorted, so `low` never exceeds `high` even on the rare row where the
  quantiles cross.
- Unknown feature keys are ignored and missing model features are left as missing, which
  LightGBM handles natively.

`predict_latest` builds today's features itself, from the raw store written by stage 1. It
runs the same shared builders training uses, on that ticker's own history, and takes the most
recent row — so the feature values a live forecast sees are identical to the ones the model
was fitted on. It also applies the same rollover: when the latest row is its candle's last
trading day, the forecast targets the next candle.

The recommendation is decided here rather than downstream, because it depends on where
this horizon's `prob_up` distribution sits — which only the build stage measures.

---

## 📦 Models and caching

- Boosters are saved to `Inference_models/<horizon>/<quantile>.txt` with a `metadata.json`
  per horizon. Both are generated artifacts, rebuilt by this stage; a fresh clone builds them
  on first launch through `backend/ai_bridge/train_service.py`.
- `metadata.json` is written **last**, so its presence guarantees the three boosters beside
  it are complete. `train_service` relies on exactly that when it decides whether any model
  exists.
- The metadata stores the feature order, so the predictor always builds the feature row in
  the exact order the model was trained on. A model and its feature list therefore travel
  together and cannot drift apart.
- It also stores the conformal offset, the volatility columns the band is scaled by, and
  the recommendation cut points. All three are measured during the build, so a shipped
  model carries everything needed to reproduce the band it was calibrated to produce.
- The predictor loads a horizon's models on first use and caches them, so the first call pays
  the load cost and later calls are fast. A retrain is picked up when the serving process
  restarts.