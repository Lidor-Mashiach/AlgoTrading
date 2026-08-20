import { useCallback, useEffect, useRef, useState } from "react";

import {
  CURRENCY_DISPLAY, DAILY_ROWS_FOR, HISTORY_PERIODS, SPARK_ROWS, currencyMeta, marketMeta,
} from "./catalog.js";
import {
  dailySeries, forecast, latestSessions, listCurrencies, listIndices, listMarket,
} from "./api.js";
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
  How often the page asks whether a newer session exists, once it is up.

  Five minutes, and a single request.

  The backend checks Yahoo once an hour, so at most one of these passes in twelve finds
  anything. Twenty seconds meant a hundred and eighty passes to catch one event, which
  was work done for its own sake.

  It is not simply set to an hour to match, because the two timers are independent: a
  page that asks on the hour can land moments before the backend does, and would then
  show yesterday for the best part of an hour. Five minutes bounds that at five, for
  twelve requests an hour against a local database.
*/
const WATCH_MS = 5 * 60 * 1000;

/*
  How many incomplete reloads to sit through before accepting one anyway.

  A reload that does not bring back every index is normally the backend refusing to
  serve while it writes new rows, and the right response is to ask again in a moment
  rather than to render what happened to get through. But an index that is genuinely
  empty would never complete, and waiting on it forever would leave the page retrying
  three seconds apart for the rest of the session. After this many tries the partial
  result is accepted and the page settles, having lost nothing except that one index.
*/
const PARTIAL_ATTEMPTS = 5;

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
  The newest session the freshness map holds for the indices.

  Only the indices, because the header reports the market rather than the reference
  panels, and a currency pair publishing on its own schedule must not move it.

  Dates are ISO strings, so comparing them as text orders them correctly.
*/
export function newestIndexSession(sessions, indexSymbols) {
  if (!sessions || !indexSymbols) return null;

  let newest = null;
  for (const symbol of indexSymbols) {
    const date = sessions[symbol];
    if (typeof date === "string" && (newest === null || date > newest)) newest = date;
  }
  return newest;
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

  // Read by the watcher, which runs outside React's render and needs the current value
  // rather than the one captured when the effect was created.
  const bootedRef = useRef(false);

  const [indices, setIndices] = useState([]);
  const [indexQuotes, setIndexQuotes] = useState([]);
  const [currencyQuotes, setCurrencyQuotes] = useState([]);
  const [marketQuotes, setMarketQuotes] = useState([]);
  const [dataDate, setDataDate] = useState(null);

  // The date the header is currently showing, readable from the watcher. Same reason as
  // bootedRef: the effect is created once and would otherwise keep reading the value
  // that existed when it was created.
  const dataDateRef = useRef(null);

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

  // The freshness map behind what is currently rendered. The watcher compares the whole
  // map, so a session gained by any single exchange is enough to trigger a reload.
  const seenRef = useRef(null);

  // The freshness map behind what is rendered, as an object. A forecast compares against
  // this ticker's own entry, never against the newest date on screen: those differ
  // legitimately, because one exchange can publish a session before another.
  const seenMapRef = useRef(null);

  // Consecutive reloads that came back short of a full set of indices.
  const partialRef = useRef(0);

  /*
    The number of the newest reload to have started.

    Two of them can be in flight at once, because a forecast starts one of its own while
    the watcher is free to start another. They take a few hundred milliseconds and can
    finish in either order, so without this the older one is able to land last and paint
    its older picture over the newer one. Whatever it wrote would then stay, because the
    watcher had already recorded those sessions as shown.

    Only the newest reload is allowed to write. An older one that comes back late is
    dropped where it would otherwise call setState.
  */
  const loadSeqRef = useRef(0);

  /*
    Try to load everything the page needs.

    Returns two facts, because they are different questions:

      ok        enough came back to put something on the screen
      complete  every index came back
      stale     a newer reload started while this one was in flight

    They used to be one boolean, and that was the bug. A reload is normally short of
    indices because the backend is busy writing new rows and is refusing to serve, and
    treating that as a success recorded the new sessions as handled while the screen had
    only been partly redrawn. Nothing ever revisited it, because from then on the page
    believed it was already showing what the backend held, and the header sat on the
    previous day until the app was restarted.

    Failure of any kind is still treated the same way at the level below this: the reader
    does not care whether a symbol returned 503 because a sync is running or 404 because
    its table is empty. What changed is that the caller is now told whether the picture it
    just drew is whole.
  */
  const loadReference = useCallback(async () => {
    const seq = (loadSeqRef.current += 1);
    const superseded = () => seq !== loadSeqRef.current;

    try {
      if (!listsRef.current) {
        const [indexList, currencyList, marketList] = await Promise.all([
          listIndices(),
          listCurrencies(),
          listMarket(),
        ]);

        const indexSymbols = (indexList || []).map((o) => o.symbol).filter(Boolean);
        if (indexSymbols.length === 0) return { ok: false, complete: false, stale: false };

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
        Ask one symbol before asking fourteen.

        The freshness map answers even while the backend is fetching, by design, so it
        cannot say whether the data endpoints are serving yet. One request can. Without
        it, every retry during a long first sync fired fourteen calls that were all
        going to be refused, which is the flood this whole change exists to remove.
      */
      const probe = await loadQuotes("index", indexSymbols.slice(0, 1));
      if (probe.length === 0) return { ok: false, complete: false, stale: superseded() };

      const [rest, cq, mq] = await Promise.all([
        loadQuotes("index", indexSymbols.slice(1)),
        loadQuotes("currency", currencySymbols),
        loadQuotes("market", marketSymbols),
      ]);

      const iq = [...probe, ...rest];
      if (iq.length === 0) return { ok: false, complete: false, stale: superseded() };

      // A newer reload is already running against fresher data. Writing now would put
      // this older picture on the screen and leave it there.
      if (superseded()) return { ok: false, complete: false, stale: true };

      const newest = iq.reduce((latest, q) => (q.date > latest ? q.date : latest), "");

      setIndices(indexSymbols);
      setSymbol((current) => current || indexSymbols[0] || "");
      setIndexQuotes(iq);
      setCurrencyQuotes(cq);
      setMarketQuotes(mq);
      setDataDate(newest);
      dataDateRef.current = newest;
      setBooted(true);
      bootedRef.current = true;

      return { ok: true, complete: iq.length === indexSymbols.length, stale: false };
    } catch {
      return { ok: false, complete: false, stale: superseded() };
    }
  }, []);

  /*
    Open the page, then keep watching for a newer session.

    Two jobs, one loop.

    Before the page exists, this is the gate. The backend reports itself unavailable for
    the whole of its startup cycle, so the waiting screen holds until the store is
    current and the interface can never open on a stale day.

    After that, each pass costs one request: the freshness map for every symbol. The
    fourteen data calls follow only when that map differs from what is on screen, so a
    quiet page makes twelve requests an hour and a session gained by any exchange is
    picked up within the watch interval.

    A reload is triggered by either of two things, and the second is the safety net:

      the map changed   something has moved since the last pass
      the map is ahead  the map holds a newer index session than the header shows

    The first is a comparison of one pass against the last, and it can only fire once per
    change. The second is a comparison against what is actually on the screen, so it does
    not care how the screen fell behind or how long ago. A reload that was interrupted
    part way through is corrected on the very next pass, and both readings come out of
    the request that was going to be made anyway.

    A pass that fails leaves the screen exactly as it was, because state is written only
    when a load actually returns data.
  */
  useEffect(() => {
    let alive = true;
    let timer;

    const attempt = async () => {
      let wait = POLL_MS;

      try {
        const map = await latestSessions();
        const signature = JSON.stringify(map);

        const stored = newestIndexSession(map, listsRef.current?.indexSymbols);
        const behind = Boolean(stored && dataDateRef.current && stored > dataDateRef.current);

        if (!bootedRef.current || signature !== seenRef.current || behind) {
          const { ok, complete, stale } = await loadReference();

          if (stale) {
            // A newer reload took over. It writes, and the next pass confirms.
            wait = POLL_MS;
          } else if (ok && (complete || partialRef.current >= PARTIAL_ATTEMPTS)) {
            // A whole picture, or one index that is never going to answer. Either way
            // this pass is done and the next one can wait out the full interval.
            seenRef.current = signature;
            seenMapRef.current = map;
            partialRef.current = 0;
            wait = WATCH_MS;
          } else if (ok) {
            // Something was drawn, but not all of it. The screen keeps what came back
            // and the pass is deliberately NOT recorded, so this repeats shortly and
            // finishes the job once the backend is free.
            partialRef.current += 1;
            wait = POLL_MS;
          } else {
            // The backend is busy or not up. Ask again shortly and change nothing.
            wait = POLL_MS;
          }
        } else {
          wait = WATCH_MS;
        }
      } catch {
        // The backend is busy or not up. Ask again shortly and change nothing.
        wait = POLL_MS;
      }

      if (!alive) return;
      timer = setTimeout(attempt, wait);
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

        /*
          Reload the panels only when this forecast proves them out of date.

          The band already carries the session it was built on, so the comparison is
          free: no request is made to discover it.

          Compared against this ticker's own entry in the freshness map, not against the
          newest date on screen. Those are different things: the header shows the newest
          session held for any index, so a forecast for a ticker whose exchange has not
          published yet reports an older date perfectly correctly. Comparing against the
          header fired a fourteen request reload on every press.
        */
        const known = seenMapRef.current ? seenMapRef.current[symbol] : null;
        if (result.based_on_date && known && result.based_on_date !== known) {
          loadReference();
        }
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
  }, [symbol, horizon, loadReference]);

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