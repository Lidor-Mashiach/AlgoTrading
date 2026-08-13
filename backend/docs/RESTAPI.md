## Endpoints

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
