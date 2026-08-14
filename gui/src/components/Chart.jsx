import { useEffect, useRef, useState } from "react";
import { price, percent, date, dateShort } from "../format.js";

/*
  The chart, drawn by hand.

  A charting library was the obvious choice and the wrong one. This view needs candles
  and a shaded forecast band and dashed gridlines that pass behind the bodies and a
  vertical divider and price labels pinned to the band edges. Every one of those is a
  fight with a library's own opinions, while in plain SVG each is a line of arithmetic.
  The result is also the only dependency free part of the page.

  Geometry is measured rather than assumed. The panel is handed whatever height the
  layout has left over, and the drawing is rebuilt in real pixels to fill it, so the
  chart grows with the window instead of holding a fixed shape and letterboxing itself.
*/

// Top padding leaves a clear strip for the style toggle. The toggle used to float over
// the top right of the plot, which is exactly where the forecast band and its upper
// label sit, so the two collided on every chart with an upward band.
const PAD = { left: 62, right: 24, top: 46, bottom: 34 };

// The forecast is a single candle, so it gets a single candle's worth of room plus a
// little air. Giving it more would push the history into a narrow strip and make the
// context unreadable, which is the opposite of what the band is there to show.
/*
  The forecast gets a third of the plot, and the history gives up two candles to pay for
  it. Squeezing three figures into two candle widths at the right edge was the whole
  reason that area kept coming out cramped, and no amount of adjusting type sizes was
  going to fix a space problem. Nine periods still read as a trend.
*/
const GAP_SLOTS = 0.5;
const FORECAST_SLOTS = 3.5;

const TICK_COUNT = 5;

// Breathing room outside the outermost gridline, as a share of the drawn range.
//
// Measuring it against the range rather than against the price is what keeps the chart
// readable. An index near 700 moving through a 27 point window would take 35 points of
// padding on a share of price, more than the whole window, and every candle would
// collapse into a thin strip across an empty panel. Against the range the air stays
// proportional to what is actually shown, at any price level.
const PAD_RATIO = 0.05;

// Clearance kept between each band edge and the edge of the plot, so the figure written
// just outside that edge always has somewhere to sit.
const BOUND_ROOM = 54;

const INK = "#1e242e";
const MUTE = "#7b8494";
const GRID = "#d7dbe2";
const BAND = "#eaedf2";
const BAND_EDGE = "#c9cfd9";
const UP = "#1a7f5a";
const DOWN = "#b2402f";

const MONO = "var(--font-num)";

// The move inside a candle is a day, a week or a month depending on the horizon, so the
// readout says which. "Change" alone would be true and useless.
const PERIOD_CHANGE = {
  daily: "Daily change",
  weekly: "Weekly change",
  monthly: "Monthly change",
};
const finite = (v) => Number.isFinite(Number(v));
const tone = (v) => (Number(v) > 0 ? UP : Number(v) < 0 ? DOWN : MUTE);

export function Chart({ candles, band, mode, onMode }) {
  const [hover, setHover] = useState(null);
  const [box, setBox] = useState({ w: 900, h: 420 });
  const wrapRef = useRef(null);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el || typeof ResizeObserver === "undefined") return undefined;
    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      if (width > 200 && height > 160) setBox({ w: Math.round(width), h: Math.round(height) });
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  if (!candles || candles.length === 0 || !band) return null;

  const { w: W, h: H } = box;
  const x0 = PAD.left;
  const x1 = W - PAD.right;
  const y0 = PAD.top;
  const y1 = H - PAD.bottom;
  const plotH = y1 - y0;

  /*
    Slot width follows the number of candles actually available. A ticker with a short
    history would otherwise draw four candles crammed into the left third with dead space
    beside them, so the window adapts instead of assuming ten.
  */
  const totalSlots = candles.length + GAP_SLOTS + FORECAST_SLOTS;
  const slotW = (x1 - x0) / totalSlots;
  const bodyW = Math.min(slotW * 0.54, 34);
  const candleX = (i) => x0 + slotW * (i + 0.5);
  const dividerX = x0 + slotW * (candles.length + 0.25);
  const bandX0 = x0 + slotW * (candles.length + 0.5);
  const bandX1 = x0 + slotW * (totalSlots - 0.1);
  const bandMidX = (bandX0 + bandX1) / 2;

  // A band with a missing edge cannot be drawn, but the history still can. Losing the
  // whole chart over one absent number would be the worse failure.
  const hasBand = finite(band.low_price) && finite(band.mid_price) && finite(band.high_price);

  /*
    The scale takes the widest of everything that must be visible: every candle edge and
    both edges of the forecast band. Reading the extremes from the candles alone would
    let a wide band run off the top of the panel, which is exactly the case the padding
    exists to absorb.
  */
  const values = [];
  for (const c of candles) {
    if (finite(c.open)) values.push(Number(c.open));
    if (finite(c.close)) values.push(Number(c.close));
  }
  if (hasBand) values.push(Number(band.low_price), Number(band.high_price));
  if (values.length === 0) return null;

  let dataMin = Math.min(...values);
  let dataMax = Math.max(...values);

  // A perfectly flat window has no range to divide, so give it a nominal one and centre
  // the data inside it rather than dividing by zero.
  if (dataMax === dataMin) {
    const nominal = Math.abs(dataMax) * 0.01 || 1;
    dataMin -= nominal / 2;
    dataMax += nominal / 2;
  }
  const span = dataMax - dataMin;

  // Gridlines land on the real extremes. The padding is air outside the outermost line,
  // so the axis still reads as the true high and low of the window.
  let yTop = dataMax + span * PAD_RATIO;
  let yBottom = dataMin - span * PAD_RATIO;

  /*
    Open the scale until the band has room for its own labels.

    Each bound is written just outside the band, so a band that lands near the edge of
    the plot has nowhere to put its figure. Clamping the text back inside only moved the
    collision onto the expected plate, which is what it did whenever a flat band sat near
    the top. Solving it on the scale instead of on the text means the room is always
    there and no label ever has to be pushed anywhere.

    The gridlines are unaffected. They stay on the real minimum and maximum, and this
    only widens the air outside them.
  */
  if (hasBand && plotH > BOUND_ROOM * 3) {
    const k = BOUND_ROOM / plotH;
    const high = Number(band.high_price);
    const low = Number(band.low_price);
    for (let i = 0; i < 3; i += 1) {
      yTop = Math.max(yTop, yBottom + (high - yBottom) / (1 - k));
      yBottom = Math.min(yBottom, (low - yTop * k) / (1 - k));
    }
  }

  const scaleY = (v) => y1 - ((Number(v) - yBottom) / (yTop - yBottom)) * plotH;

  const ticks = [];
  for (let i = 0; i < TICK_COUNT; i += 1) ticks.push(dataMin + (span / (TICK_COUNT - 1)) * i);

  const yHigh = hasBand ? scaleY(band.high_price) : 0;
  const yLow = hasBand ? scaleY(band.low_price) : 0;
  const yMid = hasBand ? scaleY(band.mid_price) : 0;


  /*
    Band labels are set in three weights rather than one string.

    "779.11 +0.86%" read as a single expression, as though the percentage were being
    added to the price. A bold price, a gap, and a lighter coloured percentage read as
    two facts about one number, which is what they are.
  */
  /*
    The forecast figures.

    This area kept coming out cramped because it was three strings of the same weight
    fighting for the same narrow column. It is now set as a range with a hierarchy: the
    expected close is the headline and the two bounds are its edges, quieter and smaller,
    each pinned to the line it describes.

    The headline sits on a solid plate rather than straight on the shaded band. Reversing
    it out separates it from the block behind it without needing a gap that the band may
    not be tall enough to give.
  */
  const EDGE_PRICE = 12;
  const EDGE_PCT = 10.5;
  const EYEBROW = 8.5;

  const textWidth = (parts) =>
    parts.reduce((sum, [text, size, gap = 0]) => sum + String(text).length * size * 0.58 + gap, 0);

  // Centre on the band, then hold inside the forecast zone. The left stop is the
  // divider, so a wide label can never spill back across it onto the history.
  const clampX = (width) => {
    const half = width / 2;
    const left = dividerX + 6 + half;
    const right = W - 6 - half;
    return left > right ? (left + right) / 2 : Math.min(Math.max(bandMidX, left), right);
  };

  /*
    One shape for all three figures.

    The expected close was set apart on a dark plate, which made it the loudest thing on
    a white chart and broke the family the three numbers belong to. They are the same
    kind of fact about the same range, so they are written the same way. What separates
    the expected close is the weight of its rule and the ink of its price, not a
    different treatment altogether.
  */
  const Figure = ({ y, priceValue, pct, eyebrow, lead }) => {
    const parts = [
      ...(eyebrow ? [[eyebrow, EYEBROW * 1.35, 8]] : []),
      [price(priceValue), EDGE_PRICE, 7],
      ["|", EDGE_PCT, 7],
      [percent(pct), EDGE_PCT, 0],
    ];
    return (
      <text x={clampX(textWidth(parts))} y={y} textAnchor="middle">
        {eyebrow && (
          <tspan fill={MUTE} fontFamily={MONO} fontSize={EYEBROW} letterSpacing="0.12em">
            {eyebrow}
          </tspan>
        )}
        <tspan fill={lead ? INK : MUTE} fontSize={EDGE_PRICE} fontWeight={lead ? 700 : 600}
               dx={eyebrow ? 8 : 0}>
          {price(priceValue)}
        </tspan>
        <tspan fill={GRID} fontSize={EDGE_PCT} dx="7">|</tspan>
        <tspan fill={tone(pct)} fontSize={EDGE_PCT} fontWeight={lead ? 700 : 600} dx="7">
          {percent(pct)}
        </tspan>
      </text>
    );
  };

  /*
    The expected figure stays glued to its own line, and the two bounds give way to it.

    Each bound already has a rule drawn at the exact edge it describes, so its text can
    move a little without losing what it points at. The expected close has no such
    freedom, since a label that drifts off the line stops meaning the line.
  */
  // A figure is about 14 pixels tall and sits mostly above its baseline, so the gaps
  // below are what is left between the blocks rather than between the baselines.
  const midY = yMid - 9;
  const highY = Math.max(Math.min(yHigh - 11, midY - 24), y0 + 12);
  const lowY = Math.min(Math.max(yLow + 21, midY + 26), y1 - 6);

  // The readout follows the pointer, and falls back to the most recent candle so the
  // strip above the plot is never empty.
  const readout = hover ? hover.candle : candles[candles.length - 1];

  const linePoints = candles
    .map((c, i) => `${candleX(i).toFixed(1)},${scaleY(c.close).toFixed(1)}`)
    .join(" ");

  return (
    <div className="chart-panel" ref={wrapRef}>
      <div className="chart-toggle" role="group" aria-label="Chart style">
        <button aria-pressed={mode === "candles"} onClick={() => onMode("candles")}>
          Candles
        </button>
        <button aria-pressed={mode === "line"} onClick={() => onMode("line")}>
          Line
        </button>
      </div>

      {/*
        A fixed readout instead of a floating tooltip.

        A box that followed the pointer had to go somewhere, and every somewhere was on
        top of the chart: above the candle, below it, or over its neighbours. Flipping it
        only moved which part got covered. Pinned in the strip the panel already reserves,
        it covers nothing, sits in the same place every time so the eye knows where to
        look, and can show the latest candle when nothing is hovered rather than
        appearing and vanishing.
      */}
      <div className="chart-readout">
        <span className="ro-date">{date(readout.date)}</span>
        <span className="ro-pair"><i>Open</i>{price(readout.open)}</span>
        <span className="ro-pair"><i>Close</i>{price(readout.close)}</span>
        <span className="ro-pair">
          <i>{PERIOD_CHANGE[band.horizon] || "Change"}</i>
          <b className={readout.changePct >= 0 ? "up" : "down"}>{percent(readout.changePct)}</b>
        </span>
      </div>

      <svg className="chart-svg" viewBox={`0 0 ${W} ${H}`} width={W} height={H} role="img"
           aria-label={`Price history and forecast for ${band.ticker}`}>
        {/* Grid first so the dashes always pass behind the bodies. */}
        {ticks.map((value, i) => (
          <g key={`tick-${i}`}>
            <line x1={x0} y1={scaleY(value)} x2={x1} y2={scaleY(value)} stroke={GRID}
                  strokeWidth="1" strokeDasharray="3 4" />
            <text x={x0 - 10} y={scaleY(value)} fill={MUTE} fontSize="10.5" fontFamily={MONO}
                  textAnchor="end" dominantBaseline="central">
              {price(value)}
            </text>
          </g>
        ))}

        {hasBand && (
          <>
            <rect className="band-block" x={bandX0} y={yHigh} width={bandX1 - bandX0}
                  height={Math.max(yLow - yHigh, 2)} fill={BAND} rx="4" />

            <line x1={bandX0} y1={yHigh} x2={bandX1} y2={yHigh} stroke={BAND_EDGE} strokeWidth="1" />
            <line x1={bandX0} y1={yLow} x2={bandX1} y2={yLow} stroke={BAND_EDGE} strokeWidth="1" />
            <line className="band-mid" x1={bandX0} y1={yMid} x2={bandX1} y2={yMid} stroke={INK}
                  strokeWidth="2.6" strokeLinecap="round" />

            <Figure y={highY} priceValue={band.high_price} pct={band.high_pct} />
            <Figure y={midY} priceValue={band.mid_price} pct={band.mid_pct} eyebrow="EXPECTED" lead />
            <Figure y={lowY} priceValue={band.low_price} pct={band.low_pct} />
          </>
        )}

        {/* Where recorded history stops and the forecast begins. */}
        <line className="divider" x1={dividerX} y1={y0 - 6} x2={dividerX} y2={y1} stroke={INK}
              strokeWidth="1.2" strokeDasharray="5 4" opacity="0.6" />

        {/* History. */}
        {mode === "line" ? (
          <>
            <polyline points={linePoints} fill="none" stroke={INK} strokeWidth="1.9"
                      strokeLinejoin="round" strokeLinecap="round" />
            {candles.map((c, i) => (
              <circle key={`dot-${c.date}`} cx={candleX(i)} cy={scaleY(c.close)} r="2.8"
                      fill={c.close >= c.open ? UP : DOWN} />
            ))}
          </>
        ) : (
          candles.map((c, i) => {
            const yA = scaleY(Math.max(c.open, c.close));
            const yB = scaleY(Math.min(c.open, c.close));
            return (
              <rect key={`body-${c.date}`} x={candleX(i) - bodyW / 2} y={yA} width={bodyW}
                    height={Math.max(yB - yA, 1.8)} fill={c.close >= c.open ? UP : DOWN}
                    rx="1.5" className="candle-body" />
            );
          })
        )}

        {/* Date axis. */}
        {candles.map((c, i) => (
          <text key={`x-${c.date}`} className="axis-x" x={candleX(i)} y={y1 + 18} fill={MUTE}
                fontSize="10" fontFamily={MONO} textAnchor="middle">
            {dateShort(c.date)}
          </text>
        ))}

        {/* Full height hit areas. Aiming at a thin body is fussy, aiming at a column is
            not, and the target should never be harder than the thing it represents. */}
        {candles.map((c, i) => (
          <rect key={`hit-${c.date}`} className="candle-hit" x={candleX(i) - slotW / 2} y={y0}
                width={slotW} height={plotH} fill="transparent"
                onMouseEnter={() =>
                  setHover({ candle: c, index: i })}
                onMouseLeave={() => setHover(null)} />
        ))}
      </svg>

      {/*
        The tooltip flips below the candle when there is not enough room above it, and
        its horizontal position is clamped inside the panel. It used to sit above
        unconditionally, so a candle near the top of the plot pushed it past the panel
        edge where overflow clipped it in half.
      */}

    </div>
  );
}

export function ChartPlaceholder() {
  return (
    <div className="chart-panel">
      <div className="chart-empty">
        <div className="chart-empty-title">Nothing plotted yet</div>
        <p className="chart-empty-note">
          Pick an index and a horizon, then select Forecast to draw the price history and
          the expected range.
        </p>
      </div>
    </div>
  );
}
