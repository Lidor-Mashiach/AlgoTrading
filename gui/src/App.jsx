import { useCallback, useEffect, useRef, useState } from "react";

import {
  CURRENCY_DISPLAY, DAILY_ROWS_FOR, HISTORY_PERIODS, SPARK_ROWS, currencyMeta, marketMeta,
} from "./catalog.js";
import { dailySeries, forecast, listCurrencies, listIndices, listMarket } from "./api.js";
import { latestQuote, toCandles } from "./periods.js";

import { TopBar } from "./components/TopBar.jsx";
import { TickerBar } from "./components/TickerBar.jsx";
import { SidePanel } from "./components/SidePanel.jsx";
import { Controls } from "./components/Controls.jsx";
import { Chart, ChartPlaceholder } from "./components/Chart.jsx";
import { ResultsPanel } from "./components/ResultsPanel.jsx";
import { BootScreen, ForecastOverlay } from "./components/Overlays.jsx";

const POLL_MS = 3000;

/*
  Fill in any band price the API left empty.

  predictor.py returns null prices when it cannot find an anchor close, while the
  percentages are always present. The chart has the same closes in hand, so the last one
  it drew is a correct anchor and the three prices can be rebuilt from it. Without this a
  band that is perfectly well defined in percentage terms would refuse to draw.
*/
export function withPrices(band, candles) {
  const anchor = Number.isFinite(band.anchor_price)
    ? Number(band.anchor_price)
    : candles.length
      ? candles[candles.length - 1].close
      : null;

  if (anchor === null || !Number.isFinite(anchor)) return band;

  const fill = (value, pct) =>
    Number.isFinite(value) ? Number(value)
      : Number.isFinite(pct) ? anchor * (1 + Number(pct) / 100)
        : null;

  return {
    ...band,
    anchor_price: anchor,
    low_price: fill(band.low_price, band.low_pct),
    mid_price: fill(band.mid_price, band.mid_pct),
    high_price: fill(band.high_price, band.high_pct),
  };
}

/*
  Fetch a quote per symbol, tolerating the ones that fail.

  A single ticker with no rows yet must not take the whole row down with it, so these
  are settled individually and the failures are dropped. Whether enough came back to
  open the interface is decided by the caller, not here.
*/
async function loadQuotes(kind, symbols) {
  const settled = await Promise.allSettled(
    symbols.map((s) => dailySeries(kind, s, SPARK_ROWS)));

  return symbols
    .map((symbol, i) => {
      if (settled[i].status !== "fulfilled") return null;
      const quote = latestQuote(settled[i].value);
      return quote ? { symbol, ...quote } : null;
    })
    .filter(Boolean);
}

export default function App() {
  // Until this is true the interface does not exist. Not hidden behind a dialog, not
  // rendered empty with placeholders: not mounted. It is the one guarantee that a
  // half loaded page can never reach the screen.
  const [booted, setBooted] = useState(false);

  const [indices, setIndices] = useState([]);
  const [indexQuotes, setIndexQuotes] = useState([]);
  const [currencyQuotes, setCurrencyQuotes] = useState([]);
  const [marketQuotes, setMarketQuotes] = useState([]);
  const [dataDate, setDataDate] = useState(null);

  const [symbol, setSymbol] = useState("");
  const [horizon, setHorizon] = useState("daily");
  const [candles, setCandles] = useState(null);
  const [band, setBand] = useState(null);
  const [mode, setMode] = useState("candles");

  const [forecasting, setForecasting] = useState(false);

  // Every forecast run carries a number. Cancelling bumps it, so a reply that was
  // already in flight when the user walked away lands on a stale number and is dropped
  // instead of quietly filling the screen they just dismissed.
  const runRef = useRef(0);

  // The option lists do not change while the app is open, so they are fetched once and
  // kept. Re asking for them on every boot attempt was three requests per cycle that
  // could only ever return the same answer.
  const listsRef = useRef(null);

  /*
    Try to load everything the page needs. Returns whether it succeeded.

    Success means real data, not merely a response. An empty ticker list, or a set of
    symbols that all failed, is a database that exists but is not populated yet, and
    that is still a reason to wait. Every failure is treated the same way on purpose:
    the reader does not care whether the backend answered 503 because a sync is running
    or 404 because a table is empty, and an earlier version that only recognised 503
    let every other case through to a shell with no data in it.
  */
  const loadReference = useCallback(async () => {
    try {
      if (!listsRef.current) {
        const [indexList, currencyList, marketList] = await Promise.all([
          listIndices(),
          listCurrencies(),
          listMarket(),
        ]);

        const indexSymbols = (indexList || []).map((o) => o.symbol).filter(Boolean);
        if (indexSymbols.length === 0) return false;

        // The currency panel is an explicit list rather than everything the backend
        // syncs, so ordering comes from CURRENCY_DISPLAY and unlisted pairs are never
        // asked for.
        const offered = new Set((currencyList || []).map((o) => o.symbol));

        listsRef.current = {
          indexSymbols,
          currencySymbols: CURRENCY_DISPLAY.filter((s) => offered.has(s)),
          marketSymbols: (marketList || []).map((o) => o.symbol).filter(Boolean),
        };
      }

      const { indexSymbols, currencySymbols, marketSymbols } = listsRef.current;

      /*
        Probe with one request before asking for twelve.

        The option lists answer normally during a sync, so the only way to find out
        whether the database holds rows is to ask for some. Asking for all of them meant
        a dozen requests every three seconds, each rejected, for as long as the first
        sync took. One probe answers the same question.
      */
      const probe = await loadQuotes("index", indexSymbols.slice(0, 1));
      if (probe.length === 0) return false;

      const [rest, cq, mq] = await Promise.all([
        loadQuotes("index", indexSymbols.slice(1)),
        loadQuotes("currency", currencySymbols),
        loadQuotes("market", marketSymbols),
      ]);

      const iq = [...probe, ...rest];
      if (iq.length === 0) return false;

      setIndices(indexSymbols);
      setSymbol((current) => current || indexSymbols[0] || "");
      setIndexQuotes(iq);
      setCurrencyQuotes(cq);
      setMarketQuotes(mq);
      setDataDate(iq.reduce((latest, q) => (q.date > latest ? q.date : latest), ""));
      setBooted(true);
      return true;
    } catch {
      return false;
    }
  }, []);

  /*
    Keep asking until the data is in, then stop.

    This is the only thing that gates the page. The moment the backend has a populated
    dataset the whole interface appears, filled in and usable, whatever is still being
    built behind it. End of day figures do not change once loaded, so this stops on the
    first success rather than polling forever.
  */
  useEffect(() => {
    let alive = true;
    let timer;

    const attempt = async () => {
      const done = await loadReference();
      if (!alive || done) return;
      timer = setTimeout(attempt, POLL_MS);
    };

    attempt();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [loadReference]);

  // A chart belongs to one index and one horizon. Changing either makes what is drawn
  // no longer an answer to what is selected, so it comes down.
  useEffect(() => {
    setCandles(null);
    setBand(null);
  }, [symbol, horizon]);

  const runForecast = useCallback(() => {
    if (!symbol) return;
    const run = (runRef.current += 1);
    setForecasting(true);

    const attempt = async () => {
      if (runRef.current !== run) return;
      try {
        const result = await forecast(symbol, horizon);
        const rows = await dailySeries("index", symbol, DAILY_ROWS_FOR[horizon]);
        if (runRef.current !== run) return;

        const drawn = toCandles(rows, horizon, HISTORY_PERIODS);
        setCandles(drawn);
        setBand(withPrices(result, drawn));
        setForecasting(false);
      } catch {
        /*
          Every failure keeps this dialog, and this dialog always has Cancel.

          A forecast during a pipeline run answers 503. An earlier version read that as
          a sync and swapped in a dialog with no way out, half a second after the button
          was pressed. Whatever the reason a forecast is not ready, it is this dialog's
          business, and the person who asked for it can always stop waiting.
        */
        if (runRef.current !== run) return;
        setTimeout(attempt, POLL_MS);
      }
    };

    attempt();
  }, [symbol, horizon]);

  const cancelForecast = useCallback(() => {
    runRef.current += 1;
    setForecasting(false);
  }, []);

  if (!booted) return <BootScreen />;

  const hasChart = Boolean(candles && candles.length > 0 && band);

  return (
    <div className="app">
      <TopBar dataDate={dataDate} />
      <TickerBar quotes={indexQuotes} />

      {/*
        The chart takes the centre and everything that is not the chart is stacked down
        one side. The controls used to sit in a full width strip above the plot, which
        spent a whole band of the page on two dropdowns and a button, and the reference
        column ran out halfway down and left dead space under it. Both problems are the
        same problem, and one column solves it.
      */}
      <main className="main">
        <section className="stage">
          {hasChart ? (
            <Chart candles={candles} band={band} mode={mode} onMode={setMode} />
          ) : (
            <ChartPlaceholder />
          )}
          {hasChart && <ResultsPanel band={band} />}
        </section>

        <aside className="side">
          <Controls
            indices={indices}
            symbol={symbol}
            horizon={horizon}
            onSymbol={setSymbol}
            onHorizon={setHorizon}
            onForecast={runForecast}
            busy={forecasting}
          />

          {/* Only the reference panels scroll. The selectors and the button stay put. */}
          <div className="side-scroll">
            <SidePanel title="Currencies" rows={currencyQuotes} metaFor={currencyMeta} />
            <SidePanel title="Market" rows={marketQuotes} metaFor={marketMeta} />
          </div>
        </aside>
      </main>

      {forecasting && <ForecastOverlay onCancel={cancelForecast} />}
    </div>
  );
}
