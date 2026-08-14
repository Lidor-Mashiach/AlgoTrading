import { useState } from "react";
import { AssetIcon } from "./Glyphs.jsx";
import { price, signed, percent, direction, decimalsFor } from "../format.js";

/*
  The reference columns: currencies and market indicators.

  Both are reference, never selectable. Nothing here can be forecast, so nothing here
  invites a click. Rows that have not arrived yet show a dash rather than an animation,
  which keeps the column still while the rest of the page settles.

  Hovering a market row explains what the number means and which direction is which. A
  yield or an index is only useful to someone who already knows how to read it, and one
  short line costs nothing to a reader who does. Only rows that carry a hint respond.

  The hint is anchored to the row and opens leftward, and this is the whole reason it
  works. Following the pointer with a left coordinate meant the box was laid out in
  whatever space remained to its right, so near the edge of the window it had nowhere to
  go and collapsed into a column one word wide. Pinning its right edge to the row gives
  it the entire page to open into, at any pointer position.
*/
function AssetRow({ quote, meta, onHint }) {
  const known = quote.price !== undefined && quote.price !== null;

  const show = (event) => {
    if (!meta.hint) return;
    const rect = event.currentTarget.getBoundingClientRect();
    onHint({
      text: meta.hint,
      right: window.innerWidth - rect.left + 12,
      top: Math.min(Math.max(rect.top + rect.height / 2, 60), window.innerHeight - 60),
    });
  };

  return (
    <div className="asset-row" onMouseEnter={show} onMouseLeave={() => onHint(null)}>
      <AssetIcon glyph={meta.glyph} size={30} />

      <div className="asset-label">
        <div className="asset-name">{meta.name}</div>
        {meta.sub && <div className="asset-sub">{meta.sub}</div>}
      </div>

      <div className="asset-figures">
        {known ? (
          <>
            <div className="asset-price num">{price(quote.price)}</div>
            <div className={`asset-change num ${direction(quote.change)}`}>
              {signed(quote.change, decimalsFor(quote.price))} ({percent(quote.changePct)})
            </div>
          </>
        ) : (
          <div className="asset-price num muted">&ndash;</div>
        )}
      </div>
    </div>
  );
}

export function SidePanel({ title, rows, metaFor }) {
  const [hint, setHint] = useState(null);

  return (
    <section className="panel">
      <div className="panel-head">
        <span className="eyebrow">{title}</span>
      </div>

      {rows.length === 0 ? (
        <div className="asset-row">
          <span className="asset-sub">Waiting for data</span>
        </div>
      ) : (
        rows.map((quote) => (
          <AssetRow key={quote.symbol} quote={quote} meta={metaFor(quote.symbol)} onHint={setHint} />
        ))
      )}

      {hint && (
        <div className="hint" style={{ right: hint.right, top: hint.top }}>
          {hint.text}
        </div>
      )}
    </section>
  );
}
