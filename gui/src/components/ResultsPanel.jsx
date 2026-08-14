import { price, signed, percent, ratioAsPercent, date, decimalsFor } from "../format.js";

/*
  The numbers behind the picture, as one horizontal band under the chart.

  Seven cells on one row, always. An auto fitting grid was wrapping the last cell onto a
  second row and leaving six empty slots beside it, which read as a mistake rather than a
  layout. A fixed seven column track keeps the band a band.

  The chart shows the shape of the forecast and this row gives the figures exactly. Both
  read from the same band, so they can never disagree. Percentages come straight from the
  API and the money amounts are derived from the anchor, which is the last recorded close
  and therefore the point every percentage is measured against.
*/

const VERDICT_CLASS = { Long: "long", Short: "short" };

function Cell({ label, children, note }) {
  return (
    <div className="result-cell">
      <span className="eyebrow">{label}</span>
      {children}
      {note && <div className="result-note">{note}</div>}
    </div>
  );
}

function Meter({ value }) {
  return (
    <div className="meter">
      <i style={{ width: `${Math.round((Number(value) || 0) * 100)}%` }} />
    </div>
  );
}

export function ResultsPanel({ band }) {
  if (!band) return null;

  const anchor = Number(band.anchor_price);
  const move =
    Number.isFinite(anchor) && Number.isFinite(band.mid_price) ? band.mid_price - anchor : null;

  return (
    <div className="results">
      <Cell label="Position" note={`Based on ${date(band.based_on_date)}`}>
        <div className={`verdict ${VERDICT_CLASS[band.recommendation] || "flat"}`}>
          {band.recommendation}
        </div>
      </Cell>

      <Cell label="Expected" note={`${percent(band.mid_pct)} against ${price(anchor)}`}>
        <div className="result-value num">{price(band.mid_price)}</div>
      </Cell>

      <Cell label="Expected move" note="Against the last close">
        <div className={`result-value num ${move > 0 ? "up" : move < 0 ? "down" : ""}`}>
          {signed(move, decimalsFor(anchor))}
        </div>
      </Cell>

      <Cell label="Upper bound" note={percent(band.high_pct)}>
        <div className="result-value num">{price(band.high_price)}</div>
      </Cell>

      <Cell label="Lower bound" note={percent(band.low_pct)}>
        <div className="result-value num">{price(band.low_price)}</div>
      </Cell>

      <Cell label="Upside odds" note="Chance of closing above the last close">
        <div className="result-value num">{ratioAsPercent(band.prob_up)}</div>
        <Meter value={band.prob_up} />
      </Cell>

      <Cell label="Stability" note="How narrow this range is against its own history">
        <div className="result-value num">{ratioAsPercent(band.stability)}</div>
        <Meter value={band.stability} />
      </Cell>
    </div>
  );
}
