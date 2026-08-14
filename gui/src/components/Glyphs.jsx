/*
  Badges, the wordmark and sparklines, drawn rather than fetched.

  Nothing is loaded from disk or from the network, so these render instantly, survive
  being run offline and add no files to the repository.

  Badges are deliberately colourless. An earlier version gave each asset a saturated
  tint, and a bright glyph in bold on a dark disc turned out to be the hardest thing on
  the page to read: the colour fought the letterforms instead of helping them. One
  neutral disc with light text is legible at a glance, and it stops the reference
  columns from competing with the chart, which is the one place colour carries meaning.
*/

const SIZE_FOR_LENGTH = { 1: 16, 2: 15, 3: 12.5, 4: 10.5, 5: 8.6 };

export function AssetIcon({ glyph, size = 32 }) {
  const fontSize = SIZE_FOR_LENGTH[Math.min(glyph.length, 5)] || 8.6;

  return (
    <svg width={size} height={size} viewBox="0 0 34 34" aria-hidden="true" focusable="false"
         className="badge">
      <circle cx="17" cy="17" r="16" />
      <text x="17" y="17" fontFamily="var(--font-num)" fontSize={fontSize} fontWeight="700"
            textAnchor="middle" dominantBaseline="central">
        {glyph}
      </text>
    </svg>
  );
}

/*
  The mark: three candles, up then down then up, with wicks.

  The first attempt was three bars of rising height in one colour, which is the universal
  picture of signal strength and read as a wifi icon rather than a market. Wicks and the
  green red green sequence fix that: nothing else uses that shape. The favicon files are
  generated from the same coordinates.
*/
export function Mark({ size = 26 }) {
  const candles = [
    { x: 4.5, wick: [9, 28], body: [13, 25], up: true },
    { x: 13.5, wick: [5, 24], body: [8, 20], up: false },
    { x: 22.5, wick: [3, 22], body: [6, 18], up: true },
  ];

  return (
    <svg width={size} height={size} viewBox="0 0 32 32" role="img" aria-label="Algo Trade"
         className="mark">
      {candles.map((c, i) => {
        const fill = c.up ? "var(--up)" : "var(--down)";
        return (
          <g key={i} fill={fill}>
            <rect x={c.x + 1.75} y={c.wick[0]} width="1.5" height={c.wick[1] - c.wick[0]} rx="0.7" />
            <rect x={c.x} y={c.body[0]} width="5" height={c.body[1] - c.body[0]} rx="1.2" />
          </g>
        );
      })}
    </svg>
  );
}

/*
  A sparkline is shape only. No axis, no labels, no baseline, because at this size any
  of those would be noise rather than information. Colour carries the direction.
*/
export function Sparkline({ values, width = 64, height = 24 }) {
  if (!values || values.length < 2) {
    return <svg width={width} height={height} aria-hidden="true" focusable="false" />;
  }

  const low = Math.min(...values);
  const high = Math.max(...values);
  const span = high - low || 1;
  const step = width / (values.length - 1);
  const rising = values[values.length - 1] >= values[0];

  const points = values
    .map((value, i) =>
      `${(i * step).toFixed(1)},${(height - 2 - ((value - low) / span) * (height - 4)).toFixed(1)}`)
    .join(" ");

  return (
    <svg width={width} height={height} aria-hidden="true" focusable="false">
      <polyline points={points} fill="none" strokeWidth="1.6" strokeLinejoin="round"
                strokeLinecap="round" stroke={rising ? "var(--up)" : "var(--down)"} />
    </svg>
  );
}
