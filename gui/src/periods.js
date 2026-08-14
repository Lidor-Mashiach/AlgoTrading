/*
  Turning daily closes into candles.

  The API returns one row per trading day: a date and a close. Weekly and monthly views
  are built here by grouping those days and keeping the last close of each group, which
  is the period's closing price.

  Open comes from the previous period's close. The backend does not expose an open, and
  a body drawn from previous close to current close still shows direction and size
  correctly. The only thing lost is the overnight gap, which is why the first candle in
  the window is dropped rather than drawn from an open it does not have.
*/

const number = (value) => {
  // Number(null) and Number("") are both 0, which would turn a missing close into a
  // real looking price of zero and drag the whole axis down to it.
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
};

/** ISO week key. Weeks that straddle a year boundary must not split, hence ISO. */
function weekKey(iso) {
  const d = new Date(`${iso}T00:00:00Z`);
  const day = d.getUTCDay() || 7;              // Monday 1 through Sunday 7
  d.setUTCDate(d.getUTCDate() + 4 - day);      // move to the Thursday of that week
  const yearStart = new Date(Date.UTC(d.getUTCFullYear(), 0, 1));
  const week = Math.ceil(((d - yearStart) / 86400000 + 1) / 7);
  return `${d.getUTCFullYear()}-W${String(week).padStart(2, "0")}`;
}

const monthKey = (iso) => String(iso).slice(0, 7);

/**
 * Collapse daily rows into closes for the requested horizon.
 * Returns [{ date, close }] in ascending order, one entry per period.
 */
export function toPeriodCloses(rows, horizon) {
  const clean = (rows || [])
    .map((row) => ({ date: String(row.date).slice(0, 10), close: number(row.close_daily_last) }))
    .filter((row) => row.date && row.close !== null)
    .sort((a, b) => a.date.localeCompare(b.date));

  if (horizon === "daily") return clean;

  const keyOf = horizon === "weekly" ? weekKey : monthKey;
  const lastOfPeriod = new Map();
  for (const row of clean) lastOfPeriod.set(keyOf(row.date), row);
  return [...lastOfPeriod.values()];
}

/**
 * Build the candles the chart draws.
 * Returns at most `count` candles, each { date, open, close, changePct }.
 */
export function toCandles(rows, horizon, count) {
  const closes = toPeriodCloses(rows, horizon);
  const candles = [];

  for (let i = 1; i < closes.length; i += 1) {
    const open = closes[i - 1].close;
    const close = closes[i].close;
    candles.push({
      date: closes[i].date,
      open,
      close,
      changePct: open ? ((close - open) / open) * 100 : 0,
    });
  }

  return candles.slice(-count);
}

/** Latest close and its move against the one before it, for the bar and the side panels. */
export function latestQuote(rows) {
  const closes = toPeriodCloses(rows, "daily");
  if (closes.length === 0) return null;

  const last = closes[closes.length - 1];
  const previous = closes.length > 1 ? closes[closes.length - 2] : null;
  const change = previous ? last.close - previous.close : null;

  return {
    date: last.date,
    price: last.close,
    change,
    changePct: previous && previous.close ? (change / previous.close) * 100 : null,
    spark: closes.map((row) => row.close),
  };
}
