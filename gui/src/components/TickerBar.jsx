import { indexMeta } from "../catalog.js";
import { AssetIcon, Sparkline } from "./Glyphs.jsx";
import { price, signed, percent, direction, decimalsFor } from "../format.js";

/*
  The moving bar.

  The first version ran the six indices together as one continuous stream with a hairline
  between them, and it was unreadable: with a badge, two lines of text, a sparkline and
  two figures all at the same rhythm, nothing said where one index stopped and the next
  began. Each index is now a card with its own surface and a real gap around it, so the
  boundary is a shape rather than a line, and the eye can lock onto one while the row is
  still in motion.

  The track holds the same six twice and slides by exactly half its width, so the loop
  closes on itself with no visible jump. Hovering anywhere pauses the whole track, which
  is the only way a person can actually read a moving row, and the card under the pointer
  lifts to confirm what they are reading.

  Prices are the tracker's own, never the underlying index level where a tracker exists,
  because the tracker is what gets traded and what the forecast is built on.
*/
function TickerCard({ quote }) {
  const meta = indexMeta(quote.symbol);

  return (
    <article className="ticker-card">
      <AssetIcon glyph={meta.glyph} size={30} />

      <div className="ticker-id">
        <div className="ticker-name">{meta.name}</div>
        <div className="ticker-symbol">{quote.symbol}</div>
      </div>

      <Sparkline values={quote.spark} width={58} height={26} />

      <div className="ticker-figures">
        <div className="ticker-price num">{price(quote.price)}</div>
        <div className={`ticker-change num ${direction(quote.change)}`}>
          {signed(quote.change, decimalsFor(quote.price))} ({percent(quote.changePct)})
        </div>
      </div>
    </article>
  );
}

export function TickerBar({ quotes }) {
  if (!quotes || quotes.length === 0) {
    return (
      <div className="tickerbar">
        <div className="ticker-track ticker-track-still">
          <span className="eyebrow">Loading market data</span>
        </div>
      </div>
    );
  }

  // Duplicated on purpose. Half the track scrolling away reveals the copy behind it.
  return (
    <div className="tickerbar">
      <div className="ticker-track">
        {[...quotes, ...quotes].map((quote, i) => (
          <TickerCard key={`${quote.symbol}-${i}`} quote={quote} />
        ))}
      </div>
    </div>
  );
}
