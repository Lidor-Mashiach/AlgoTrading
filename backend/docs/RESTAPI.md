## Endpoints

### Latest Stored Session Per Symbol

```
GET /api/latest
```

Returns the most recent stored date for every tracked symbol, in a single call.

Exists so a client can tell whether anything has moved without asking each symbol in
turn. Every exchange publishes on its own schedule, so watching one symbol misses the
others.

Not blocked while a sync is running. A client watching for change is exactly the client
that should keep getting an answer during one.

Example response:

```json
{
  "status": "success",
  "data": { "SPY": "2026-08-18", "TA35.TA": "2026-08-17" }
}
```

### List Primary Tickers

```http
GET /api/tickers
```

Returns all supported primary ticker symbols and their available horizons.

---

### Get Primary Ticker Data

```http
GET /api/tickers/{symbol}?horizon={horizon}&limit={limit}
```

Returns historical data for a supported primary ticker.

* `symbol`: Required path parameter
* `horizon`: Required query parameter
* `limit`: Optional query parameter; must be at least `1`

Example:

```http
GET /api/tickers/AAPL?horizon=daily&limit=100
```

---

### List Supporting Tickers

```http
GET /api/supporting-tickers
```

Returns all supported supporting ticker symbols and their available horizons.

---

### Get Supporting Ticker Data

```http
GET /api/supporting-tickers/{symbol}?horizon={horizon}&limit={limit}
```

Returns historical data for a supported supporting ticker.

* `symbol`: Required path parameter
* `horizon`: Required query parameter
* `limit`: Optional query parameter; must be at least `1`

Example:

```http
GET /api/supporting-tickers/SPY?horizon=daily&limit=50
```

---

### List Currencies

```http
GET /api/currencies
```

Returns all supported currencies and their available horizons.

---

### Get Currency Data

```http
GET /api/currencies/{symbol}?horizon={horizon}&limit={limit}
```

Returns historical data for a supported currency.

* `symbol`: Required path parameter
* `horizon`: Required query parameter
* `limit`: Optional query parameter; must be at least `1`

Example:

```http
GET /api/currencies/USD?horizon=daily&limit=30
```

---

### Generate a Forecast

```http
GET /api/predictions/{symbol}?horizon={horizon}
```

Generates a forecast for a supported primary ticker.

* `symbol`: Required path parameter
* `horizon`: Required query parameter

Example:

```http
GET /api/predictions/AAPL?horizon=daily
```