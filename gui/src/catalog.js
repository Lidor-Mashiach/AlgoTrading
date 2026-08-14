/*
  Presentation data for every symbol the backend serves.

  The backend answers with raw Yahoo symbols. Those are precise and unreadable, so each
  one gets a name a person would recognise and a short badge. The symbol still shows
  under an index, because that is the instrument actually being traded, but not under a
  currency pair, where "USDILS=X" is a Yahoo internal and tells a reader nothing.

  The lists of symbols are NOT hardcoded anywhere in the app. They come from the list
  endpoints at runtime. This file only decides how a symbol looks once it arrives, and
  falls back gracefully for anything it has not seen.
*/

export const HORIZONS = [
  { value: "daily", label: "Daily" },
  { value: "weekly", label: "Weekly" },
  { value: "monthly", label: "Monthly" },
];

// How many past periods the chart draws. One number, used by the axis and the layout.
//
// Nine rather than ten. The tenth candle was worth less than the room it took from the
// forecast, which is the part of this chart a person came to read.
export const HISTORY_PERIODS = 9;

// Daily rows to request per horizon. Weekly and monthly are folded from daily rows in
// the browser, so each needs enough trading days to cover HISTORY_PERIODS periods with
// room for holidays and short weeks.
export const DAILY_ROWS_FOR = { daily: 16, weekly: 95, monthly: 340 };

// Rows behind each sparkline in the moving bar.
export const SPARK_ROWS = 10;

const INDEX_META = {
  "SPY":       { name: "S&P 500",    glyph: "S&P" },
  "QQQ":       { name: "Nasdaq 100", glyph: "NDQ" },
  "TA35.TA":   { name: "TA-35",      glyph: "TA35" },
  "^TA125.TA": { name: "TA-125",     glyph: "TA125" },
  "^GDAXI":    { name: "DAX",        glyph: "DAX" },
  "^DJI":      { name: "Dow Jones",  glyph: "DJI" },
};

/*
  Which currencies the panel shows, and in what order.

  The backend syncs more pairs than are worth showing. This is the display list, and it
  is the one place to change it: a symbol not named here never reaches the panel, and
  one named here appears only if the backend actually returned it.

  Badges carry one glyph, the currency being priced. The pairs shown are both quoted in
  shekels, so the second half would be identical on every row and would say nothing.
*/
export const CURRENCY_DISPLAY = ["USDILS=X", "EURILS=X"];

const CURRENCY_META = {
  "USDILS=X": { name: "USD/ILS", glyph: "$" },
  "EURILS=X": { name: "EUR/ILS", glyph: "\u20AC" },
  "USDEUR=X": { name: "USD/EUR", glyph: "$" },
  "EURUSD=X": { name: "EUR/USD", glyph: "\u20AC" },
};

const MARKET_META = {
  "^VIX": { name: "VIX", sub: "Volatility index", glyph: "VIX",
            hint: "Swings the market expects over the next month. Higher means more fear." },
  "^TNX": { name: "US 10Y", sub: "Treasury yield", glyph: "10Y",
            hint: "Return on ten year US government debt. Higher usually weighs on shares." },
  "^IRX": { name: "US 13W", sub: "Treasury yield", glyph: "13W",
            hint: "Return on three month US debt. Tracks where short term rates are heading." },
  "DX-Y.NYB": { name: "Dollar", sub: "Dollar index", glyph: "DXY",
                hint: "The dollar against a basket of major currencies. Higher means it is stronger." },
};

function fallback(symbol) {
  const clean = String(symbol).replace(/[\^=]/g, "").split(".")[0];
  return { name: clean, glyph: clean.slice(0, 4) };
}

export const indexMeta = (symbol) => INDEX_META[symbol] || fallback(symbol);
export const currencyMeta = (symbol) => CURRENCY_META[symbol] || fallback(symbol);
export const marketMeta = (symbol) => MARKET_META[symbol] || fallback(symbol);
