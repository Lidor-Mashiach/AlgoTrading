import { HORIZONS, indexMeta } from "../catalog.js";

/*
  Three controls and nothing else.

  The button keeps one name everywhere it appears, so the action a person starts is the
  action they see running. It stays disabled while a request is open, because a second
  press would start a second poll against the same answer.
*/
export function Controls({ indices, symbol, horizon, onSymbol, onHorizon, onForecast, busy }) {
  return (
    <div className="controls">
      <label className="field">
        <span className="eyebrow">Index</span>
        <select value={symbol} onChange={(e) => onSymbol(e.target.value)} disabled={indices.length === 0}>
          {indices.length === 0 && <option value="">Loading</option>}
          {indices.map((s) => (
            <option key={s} value={s}>
              {indexMeta(s).name} ({s})
            </option>
          ))}
        </select>
      </label>

      <label className="field">
        <span className="eyebrow">Horizon</span>
        <select value={horizon} onChange={(e) => onHorizon(e.target.value)}>
          {HORIZONS.map((h) => (
            <option key={h.value} value={h.value}>
              {h.label}
            </option>
          ))}
        </select>
      </label>

      <button className="btn-forecast" onClick={onForecast} disabled={busy || !symbol}>
        Forecast
      </button>
    </div>
  );
}
