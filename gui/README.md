# 🖥️ GUI: Forecast Terminal

This directory owns everything a person sees. It is a **single page** that fits one screen and does not scroll: a moving index bar across the top, one control and reference column down the right, and the chart taking every pixel left over in the middle.

> System overview: [`../README.md`](../README.md) · REST contract: [`../backend/docs/RESTAPI.md`](../backend/docs/RESTAPI.md) · Backend design: [`../backend/docs/README.md`](../backend/docs/README.md)

---

## 📑 Table of Contents

- [Design in One Page](#-design-in-one-page)
- [Running It](#-running-it)
- [Two Ways to Serve, One Port](#-two-ways-to-serve-one-port)
- [Reading the Chart](#-reading-the-chart)
- [The Axis Rules](#-the-axis-rules)
- [Why Every Price Request Asks for Daily](#-why-every-price-request-asks-for-daily)
- [Waiting States](#-waiting-states)
- [Design Tokens](#-design-tokens)
- [Directory Map](#-directory-map)
- [Contracts the Backend Provides](#-contracts-the-backend-provides)
- [Icons](#️-icons)
- [Editing and Rebuilding](#-editing-and-rebuilding)

---

## 🎯 Design in One Page

**One page, no screens, no scrolling.** Nothing navigates. The layout is a fixed three row grid inside the viewport, and the chart is measured at run time to fill whatever height the rest of it leaves.

**The chart is the only bright surface.** The shell is slate and the chart is white. The eye lands on the forecast before it lands on anything else, which is the one thing this page exists to show.

**Everything that is not the chart lives in one column.** The controls used to sit in a full width strip above the plot, spending a whole band of the page on two dropdowns and a button, while the reference column ran out halfway down and left dead space under it. Both are the same problem and one column solves it.

**The page appears the moment a dataset exists.** Reference data is the only thing that gates it. Whatever is still being built behind the scenes, the interface is up, filled in and usable.

**Nothing on screen refers to how the forecast is produced.** The interface reports the last session it holds data for and nothing else about its own internals. Waiting states are described in terms of market data, never in terms of what is happening behind them.

**No dependency beyond React.** The chart, every badge and every sparkline are hand written SVG. There is no charting library, no icon package and no font download, so the page renders identically offline.

| Choice | Why |
|---|---|
| Hand drawn SVG chart | Candles, a shaded band, dashes behind the bodies, a divider and edge pinned labels are five fights with a library and five lines of arithmetic without one |
| Colourless badges | A saturated glyph in bold on a tinted disc was the hardest thing on the page to read. Colour belongs to the chart, where it means something |
| Relative `/api` paths | The page and the API share an origin, so no request is ever cross origin and the backend needs no CORS headers |
| `dist/` committed to git | Anyone who clones the repository can run the GUI without Node installed |
| Inline SVG badges | No image files, no network, no broken icons on a machine that has never been online |
| An explicit currency display list | The backend syncs more pairs than are worth showing, so `CURRENCY_DISPLAY` in `catalog.js` decides which reach the panel |
| Real `.ico` and PNG icons | An inline SVG covers the tab only. Chrome reads a genuine `.ico` for the application window and manifest PNGs for the taskbar tile |
| Mark colours in the markup, not in CSS | A `fill` rule on `.mark rect` beats the presentation attribute and repaints all three candles in one colour, which turns the mark back into a signal strength icon |
| A `?v=` on every icon URL | Chrome keeps favicons in a database inside its user data directory, far longer than an ordinary asset. Replacing the file left the old picture in the title bar until that directory was deleted by hand |
| Reference lists fetched, never hardcoded | Adding a ticker in `backend/config.json` makes it appear here with no edit to this directory |

---

## 🚀 Running It

The GUI is started for you. From the repository root:

```
python main.py
```

That launches the backend, serves this directory on port **5173** and opens a dedicated window on it. Closing the window stops everything.

To work on the GUI itself, with hot reload:

```
cd gui
npm install     # once, and only on a development machine
npm run dev
```

`main.py` detects `gui/node_modules` and uses the dev server when it is present.

---

## 🔌 Two Ways to Serve, One Port

Both paths listen on **5173** and both forward `/api` to the REST API on `127.0.0.1:8000`. That forwarding is the whole reason no CORS configuration exists anywhere in this project: the browser only ever sees one origin, so it has no cross origin request to block.

| | Used when | Provides |
|---|---|---|
| **Vite dev server** | `gui/node_modules` exists | Hot reload, source maps, unminified output |
| **`serve.py`** | It does not | Serves `dist/` with the standard library alone, no Node required |

`serve.py` preserves status codes on the way through, because `503` and `500` are what drive the waiting screens and flattening them would break both.

> ⚠️ Port 5173 appears in three files and they must agree: `main.py` (`GUI_PORT`), `vite.config.js` (`server.port`) and `serve.py` (`PORT`).

---

## 📈 Reading the Chart

The chart draws only after **Forecast** is pressed. Before that it holds an empty panel, because a chart with no forecast on it would be answering a question nobody asked.

Hovering a **market** row explains what the number means and which direction is which, because a yield or an index is only useful to someone who already knows how to read it. The hint is anchored by its right edge to the row and opens leftward, which is what stops it collapsing into a one word column near the edge of the window.

**The candle readout is pinned, not floating.** It sits in the strip above the plot, on the right, and shows the latest candle until the pointer picks another. A box that followed the pointer had to land somewhere, and every somewhere was on top of the chart it was describing. Flipping it above or below only changed which part got covered.

Hovering changes the readout and nothing else. An earlier version also lifted the whole column under the pointer, which put a grey block over the chart to say something the readout was already saying. The labels are written out as `Open`, `Close` and `Daily change`, and the last of those follows the horizon, because the move inside a candle is a day, a week or a month depending on which one is selected.

The **Candles** and **Line** control sits at the top left, in a strip the chart reserves for it, clear of the forecast band and its labels on the right.

| Element | Meaning |
|---|---|
| **Green body** | The period closed above where it opened |
| **Red body** | It closed below |
| **Body edges** | Open and close only. There are no wicks, and the section below explains why |
| **Dashed horizontal lines** | Price gridlines, drawn behind the bodies so they never cut across a candle |
| **Dashed vertical line** | Everything left of it is recorded history and everything right of it is forecast |
| **Shaded block** | The forecast range, from the lower bound to the upper bound |
| **Solid black line** | The expected close, labelled with its price and its move |

The three figures share one shape: `price | change`, with the rule and the colour carrying the separation between the two numbers. They are the same kind of fact about the same range, so they are written the same way. What marks the expected close is the weight of its rule and the ink of its price, not a different treatment. Setting it apart on a dark plate made it the loudest thing on a white chart and broke the family the three belong to.

The expected figure stays glued to its own line and the two bounds give way to it. Each bound already has a rule drawn at the exact edge it describes, so its text can move a little without losing what it points at, while a label that drifted off the middle line would stop meaning the line.

Labels are held inside the forecast zone. The left stop is the dashed divider, not the panel edge, so a wide label on a narrow band can never spill back over the history.

**The scale reserves room for them.** Each bound is written just outside the band, so a band that lands near the edge of the plot would have nowhere to put its figure. Clamping the text back inside only moved the collision onto the headline plate. The domain is opened instead until a fixed clearance exists above and below the band, which means no label is ever pushed anywhere. Gridlines are unaffected and stay on the real extremes.
| **Hovering a column** | Lifts that column and fills the readout above the plot |

**Open comes from the previous period's close.** The REST API exposes a close and no open, so a body is drawn from the last close to this one. Direction and size are exact and the only thing lost is an overnight gap, which is also why the oldest period in the window is dropped rather than drawn from an open it does not have.

---

## 📏 The Axis Rules

**Nine periods, not ten.** The tenth candle was worth less than the room it took from the forecast, which is the part of this chart a person came to read. The forecast now gets a third of the plot.

**Five gridlines.** The lowest sits on the true minimum and the highest on the true maximum, with three evenly spaced between them:

```
tick(n) = min + (max - min) / 4 * n        for n = 0 to 4
```

**Both extremes take the wider of two sources.** The minimum is the lowest of every candle edge **and** the lower bound of the forecast. The maximum is the highest of every candle edge **and** the upper bound. A band that projects far past recent trading therefore still lands inside the panel.

**Padding is five percent of the drawn range**, added outside the outermost gridline in each direction. Measured against the range rather than against the price, so it behaves the same on a pair quoted at 0.91 and an index quoted at 44,000.

> A share of the **price** was the first rule and it did not survive contact with real numbers. An index near 700 moving through a 27 point window would take 35 points of padding, wider than the entire window, and every candle collapsed into a thin strip across the middle of an empty panel.

**A flat window is given a nominal range** and centred inside it, so a period with no movement cannot divide by zero.

---

## 🗓️ Why Every Price Request Asks for Daily

Selecting a horizon chooses **which forecast to request**. It does not choose which data to plot. Every price series is fetched with `horizon=daily` and folded into weeks or months in the browser.

The reason is in the backend's own schema. All three horizon tables are split by **column**, not by row, so each holds one row per **trading day**. And the weekly close column is built as:

```python
out["close_weekly_last"] = df["week_id"].map(weekly_close_by_week["weekly_close"].shift(1))
```

That is the **previous** week's close, repeated on every day of the current week. It is a correct leak free feature for the model and a step function rather than a price series, so charting it would draw a staircase of two or three distinct values instead of ten weekly candles. The monthly column behaves the same way.

Folding daily closes gives real period closes with real dates and needs no backend change:

| Horizon | Daily rows requested | Folded by | Periods drawn |
|---|---|---|---|
| `daily` | 16 | Nothing | 9 |
| `weekly` | 95 | ISO week | 9 |
| `monthly` | 340 | Calendar month | 9 |

ISO week numbering is used so a week straddling a new year stays one week instead of splitting in two.

---

## ⏳ Waiting States

Two floating dialogs, and the difference between them is who may walk away.

| | Trigger | Cancel | Behaviour |
|---|---|---|---|
| **Boot** | Reference data has not loaded | ❌ None | The whole page. Nothing else is mounted until real data is in hand |
| **Forecast** | Anything other than a ready band | ✅ Yes | A dialog over a working page. Repeats every 3 seconds |

**The controls never scroll away.** The right column is a two row grid: the selectors and the Forecast button are pinned, and only the reference panels below them scroll when the window is short.

**The boot screen replaces the interface rather than covering it.** `App` returns it and nothing else while `booted` is false, so a partly loaded page is not hidden, it does not exist. An earlier version rendered the full shell with every panel reading "Waiting for data", which looked like broken software rather than software that was starting.

**Success means data, not a response.** An empty ticker list, or a set of symbols that all failed, is a database that exists but is not populated yet, and that is still a reason to wait.

**One probe per cycle, not twelve.** The option lists answer normally during a sync, so the only way to learn whether the database holds rows is to ask for some. The lists are fetched once and kept, and each retry asks a single ticker. A first sync can take minutes, and fifteen rejected requests every three seconds for all of it was noise with no purpose.

**Every failure is treated identically on purpose.** A reader does not care whether the answer was `503` because a sync is running or `404` because a table is empty. An earlier version recognised only `503` and let every other case through to a shell with nothing in it.

> ⚠️ **A forecast never raises the boot screen.** A forecast during a pipeline run answers `503`, and treating that as a sync once replaced the cancellable dialog with one that had no way out, half a second after the button was pressed. Since the interface only exists after boot, the two can no longer coexist at all.

Three different signals mean the same thing to a reader, so `api.js` folds them into one vocabulary rather than letting three components each re read HTTP details:

| Signal | Meaning |
|---|---|
| `503` | The daily sync is running |
| `500` | A first run, before anything has been built |
| `404` | A table that exists but holds no rows yet |
| No answer at all | The API has not come up |
| `200` with a status other than `ready` | The forecast is not available yet |

`api.js` folds all of these into one `NotReady` error, because they all mean the same thing to a reader.

**Cancel stops the polling and shows nothing.** A reply already in flight is dropped rather than filling in a screen the reader just dismissed, which is what the run counter in `App.jsx` is for. Pressing **Forecast** again starts a fresh cycle.

---

## 🎨 Design Tokens

Every colour lives in `:root` in `styles.css`. Two surfaces, on purpose.

| Token | Value | Role |
|---|---|---|
| `--bg` | `#222834` | Page background. Never white |
| `--surface` | `#2b3240` | Panels and cards |
| `--paper` | `#ffffff` | Chart background, the one bright surface |
| `--muted` | `#98a2b3` | Secondary text |
| `--brass` | `#d4a95f` | The single accent, used on one button, the mark and two meters |
| `--up` / `--down` | `#56b98a` / `#e0796a` | Direction. The only strongly coloured elements |

> An earlier shell was much darker. Against grey secondary text it pushed several labels close to unreadable, so the whole scale was lifted and the gap between background and muted text widened.

Type is set from system stacks with no download: a sans face for reading and a monospace face for every figure, so digits align in a column.

**Rules the copy follows.** English only, `dd/mm/yyyy` for every date, no semicolons, no long dashes, sentence case, and one name per action from the button through to the result.

---

## 🗂️ Directory Map

```
gui/
├── index.html                 Entry document
├── package.json               React and Vite, nothing else
├── vite.config.js             Dev server, port 5173, /api proxy
├── serve.py                   Static server and /api proxy, standard library only
├── public/                    Icons and manifest, copied to dist untouched
├── dist/                      Built output, committed so Node is not required to run
└── src/
    ├── main.jsx               Mounts the app
    ├── App.jsx                State, polling, waiting screens, band price fallback
    ├── api.js                 The only module that talks to REST
    ├── catalog.js             Display names, badge glyphs, row counts per horizon
    ├── periods.js             Daily rows folded into weekly and monthly candles
    ├── format.js              Dates, prices, signed changes, percentages
    ├── styles.css             Every token and every rule
    └── components/
        ├── TopBar.jsx         Wordmark and the data date
        ├── TickerBar.jsx      The moving index bar
        ├── SidePanel.jsx      Currencies and market indicators
        ├── Controls.jsx       Index, horizon, Forecast
        ├── Chart.jsx          The SVG chart
        ├── ResultsPanel.jsx   The forecast figures
        ├── Overlays.jsx       Sync and forecast dialogs
        └── Glyphs.jsx         Badges and sparklines
```

---

## 🔗 Contracts the Backend Provides

Everything this directory needs, and nothing it changes.

| Endpoint | Used for |
|---|---|
| `GET /api/tickers` | Which indices to offer. Never hardcoded here |
| `GET /api/currencies` | The currency block |
| `GET /api/supporting-tickers` | The market block |
| `GET /api/tickers/{symbol}?horizon=daily&limit=n` | Every price series and every sparkline |
| `GET /api/predictions/{symbol}?horizon=h` | The forecast band |

Symbols carry `^`, `.` and `=`, so every one is passed through `encodeURIComponent` before it enters a path.

Fields read from a band: `low_pct`, `mid_pct`, `high_pct`, `low_price`, `mid_price`, `high_price`, `anchor_price`, `stability`, `prob_up`, `recommendation`, `based_on_date`.

**A missing price is rebuilt, not dropped.** `predictor.py` returns null prices when it cannot resolve an anchor while the percentages are always present, so `withPrices` in `App.jsx` reconstructs the three prices from the last drawn close.

---

## 🖼️ Icons

Every icon is generated from the same three candle geometry as the header mark, by the script embedded in this project's build notes. Two details matter:

- **Each `.ico` frame is drawn at its own size.** Below about 24 pixels a wick is thinner than one pixel and only muddies the bodies, so the 16 and 24 pixel frames drop the wicks and widen the bodies instead. Letting one 256 pixel image be downscaled to all sizes produced a blur at the size the taskbar actually uses.
- **The URLs carry `?v=`.** Raise the number whenever an icon changes, otherwise Chrome keeps showing the previous one.

If an old icon somehow persists, the application profile is at `%TEMP%\algotrade-browser-profile` on Windows. It is a throwaway directory Chrome recreates, not the real browser profile.

---

## 🔨 Editing and Rebuilding

```
cd gui
npm run dev      # develop with hot reload
npm run build    # rebuild dist/
```

> ⚠️ **`dist/` must be rebuilt and committed after any change to `src/`.** A machine without Node serves `dist/` directly, so an uncommitted rebuild means everyone else keeps seeing the previous version.

`node_modules/` is never committed. `npm install` restores it from `package-lock.json` on any machine.
