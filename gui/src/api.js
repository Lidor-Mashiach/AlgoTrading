/*
  The one place that talks to the REST API.

  Requests go to a relative /api path with no host and no port. Vite forwards it in
  development and serve.py forwards it in production, so the page never makes a cross
  origin call and the port only ever appears in configuration, never in this code.

  The API reports being unavailable in three different shapes, and every one of them
  means the same thing to a person looking at the screen:

      503                       the daily sync is running
      500                       a first run, before anything has been built
      200 with a status field   the forecast is not ready

  So they are folded here into one small vocabulary the components can act on, rather
  than being re read as HTTP details in three separate places.
*/

const BASE = "/api";

/*
  One error for every way this can fail.

  The API reports being unavailable in several shapes, and every one of them means the
  same thing to a person looking at the screen:

      503                       the daily sync is running
      500                       a first run, before anything has been built
      404                       a table that exists but holds no rows yet
      no answer at all          the API has not come up
      200 with a status field   the forecast is not ready

  Separating them was a mistake. Only 503 raised a waiting screen, so a database that
  was created but not yet populated answered 404 and left the interface sitting empty
  with nothing to explain why. Whatever the code, the answer is the same: not yet.
*/
export class NotReady extends Error {
  constructor(detail) {
    super(detail || "not ready");
    this.name = "NotReady";
  }
}

async function request(path) {
  let response;
  try {
    response = await fetch(BASE + path, { headers: { Accept: "application/json" } });
  } catch {
    throw new NotReady("no answer");
  }

  if (!response.ok) throw new NotReady(String(response.status));

  try {
    return await response.json();
  } catch {
    throw new NotReady("bad payload");
  }
}

const encode = (symbol) => encodeURIComponent(symbol);

export function listIndices() {
  return request("/tickers").then((r) => r.data || []);
}

export function listCurrencies() {
  return request("/currencies").then((r) => r.data || []);
}

export function listMarket() {
  return request("/supporting-tickers").then((r) => r.data || []);
}

/*
  Only the daily horizon carries a real price series.

  The weekly and monthly tables hold one row per trading day, and their close columns
  repeat the previous completed period's close on every day inside the current one. That
  is correct as a leak free model feature and useless as a chart series, so every price
  request here asks for daily rows and the folding into weeks or months happens in
  periods.js. The horizon the user picks selects the forecast, not the data source.
*/
export function dailySeries(kind, symbol, limit) {
  const group = { index: "tickers", currency: "currencies", market: "supporting-tickers" }[kind];
  return request(`/${group}/${encode(symbol)}?horizon=daily&limit=${limit}`)
    .then((r) => r.data || []);
}

/*
  Ask for a forecast.

  Resolves only when a band is actually available. Anything else throws NotReady, which
  is what keeps the caller polling without needing to know why.
*/
export async function forecast(symbol, horizon) {
  const payload = await request(`/predictions/${encode(symbol)}?horizon=${horizon}`);
  if (payload.status !== "ready" || !payload.band) throw new NotReady();
  return payload.band;
}
