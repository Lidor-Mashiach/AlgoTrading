from typing import Optional, Sequence

from fastapi import FastAPI, HTTPException, Query, Request, status

from ai_bridge import forecast_service
from storage.TickersDBManager import TickersDBManager
from sync.SyncStatus import SyncStatus
from utils.ConfigLoader import ConfigLoader
from utils.ConsoleLogger import ConsoleLogger


logger = ConsoleLogger(caller="rest_main")

host, port = ConfigLoader.load_rest_settings()
tickers, supporting_tickers, currencies, horizons, periods, db_name, sync_time = ConfigLoader.load_prediction_settings()
db_manager = TickersDBManager(db_name, tickers + supporting_tickers + currencies, supporting_tickers, periods)

app = FastAPI(title="Ticker Forecast API", description="REST API for retrieving ticker data, supporting ticker data, currency data, and forecasts.", version="1.0.0")

logger.success(f"REST API initialized on {host}:{port}")


def get_client_address(request: Request) -> str:
    """Return the client's IP address and port."""
    if request.client is None:
        return "unknown"

    return f"{request.client.host}:{request.client.port}"


def ensure_not_syncing(client_address: str, resource: str) -> None:
    """Reject requests while synchronization is running."""
    if SyncStatus.is_syncing():
        logger.warning(f"Client {client_address} requested {resource} while syncing is in progress.")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Syncing is in progress. Please try again later.")


def validate_symbol(symbol: str, supported_symbols: Sequence[str]) -> None:
    """Validate that the requested symbol is supported."""
    if symbol not in supported_symbols:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Symbol '{symbol}' is not supported.")


def validate_horizon(horizon: str) -> None:
    """Validate that the requested horizon is supported."""
    if horizon not in horizons:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Horizon '{horizon}' is not supported.")


def validate_request(symbol: str, horizon: str, supported_symbols: Sequence[str], client_address: str, resource: str) -> None:
    """Run all common request validations."""
    validate_symbol(symbol, supported_symbols)
    validate_horizon(horizon)
    ensure_not_syncing(client_address, resource)


def create_symbol_options(symbols: Sequence[str]) -> list[dict]:
    """Create the response data for a symbol-list endpoint."""
    return [{"symbol": symbol, "horizons": horizons} for symbol in symbols]


def trim_data_columns(data: list[dict], horizon: str) -> list[dict]:
    """Limit the returned columns according to the horizon."""
    column_limit = 3 if horizon == "daily" else 4
    return [dict(list(row.items())[:column_limit]) for row in data]


def get_market_data(symbol: str, horizon: str, request: Request, supported_symbols: Sequence[str], category: str, limit: Optional[int]) -> dict:
    """Validate and retrieve historical data for a ticker or currency."""
    client_address = get_client_address(request)

    logger.info(f"Client {client_address} requested {category} data for {symbol} at horizon {horizon}.")

    validate_request(symbol, horizon, supported_symbols, client_address, f"{category} data")

    try:
        data = db_manager.get_data_as_dict(symbol, horizon, limit=limit)
        data = trim_data_columns(data, horizon)
    except Exception as ex:
        logger.error(ex)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to retrieve data for '{symbol}'.") from ex

    logger.success(f"Client {client_address} received {category} data for {symbol} at horizon {horizon}.")

    return {"status": "success", "data": data}


@app.get("/api/tickers", summary="List primary tickers", description="Returns all supported primary ticker symbols and their available horizons.", response_description="A list of supported primary ticker symbols.")
def list_tickers(request: Request) -> dict:
    """
    Return all supported primary tickers.

    Example:
    GET /api/tickers
    """
    client_address = get_client_address(request)
    logger.info(f"Client {client_address} requested ticker options.")
    return {"status": "success", "data": create_symbol_options(tickers)}


@app.get("/api/tickers/{symbol}", summary="Get primary ticker data", description="Returns historical data for a supported primary ticker.", response_description="Historical data for the requested ticker.")
def get_ticker_data(symbol: str, request: Request, horizon: str = Query(..., description="Requested data horizon.", examples=["daily"]), limit: Optional[int] = Query(default=None, ge=1, description="Maximum number of records.", examples=[100])) -> dict:
    """
    Return historical data for a primary ticker.

    Examples:
    GET /api/tickers/AAPL?horizon=daily
    GET /api/tickers/AAPL?horizon=daily&limit=100
    """
    return get_market_data(symbol, horizon, request, tickers, "ticker", limit)


@app.get("/api/supporting-tickers", summary="List supporting tickers", description="Returns all supported secondary ticker symbols and their available horizons.", response_description="A list of supported secondary ticker symbols.")
def list_supporting_tickers(request: Request) -> dict:
    """
    Return all supported secondary tickers.

    Example:
    GET /api/supporting-tickers
    """
    client_address = get_client_address(request)
    logger.info(f"Client {client_address} requested supporting ticker options.")
    return {"status": "success", "data": create_symbol_options(supporting_tickers)}


@app.get("/api/supporting-tickers/{symbol}", summary="Get supporting ticker data", description="Returns historical data for a supported secondary ticker.", response_description="Historical data for the requested secondary ticker.")
def get_supporting_ticker_data(symbol: str, request: Request, horizon: str = Query(..., description="Requested data horizon.", examples=["daily"]), limit: Optional[int] = Query(default=None, ge=1, description="Maximum number of records.", examples=[100])) -> dict:
    """
    Return historical data for a secondary ticker.

    Examples:
    GET /api/supporting-tickers/SPY?horizon=daily
    GET /api/supporting-tickers/SPY?horizon=daily&limit=50
    """
    return get_market_data(symbol, horizon, request, supporting_tickers, "supporting ticker", limit)


@app.get("/api/currencies", summary="List currencies", description="Returns all supported currencies and their available horizons.", response_description="A list of supported currencies.")
def list_currencies(request: Request) -> dict:
    """
    Return all supported currencies.

    Example:
    GET /api/currencies
    """
    client_address = get_client_address(request)
    logger.info(f"Client {client_address} requested currency options.")
    return {"status": "success", "data": create_symbol_options(currencies)}


@app.get("/api/currencies/{symbol}", summary="Get currency data", description="Returns historical data for a supported currency.", response_description="Historical data for the requested currency.")
def get_currency_data(symbol: str, request: Request, horizon: str = Query(..., description="Requested data horizon.", examples=["daily"]), limit: Optional[int] = Query(default=None, ge=1, description="Maximum number of records.", examples=[100])) -> dict:
    """
    Return historical data for a currency.

    Examples:
    GET /api/currencies/USD?horizon=daily
    GET /api/currencies/USD?horizon=daily&limit=30
    """
    return get_market_data(symbol, horizon, request, currencies, "currency", limit)


@app.get("/api/predictions/{symbol}", summary="Generate a ticker forecast", description="Generates a forecast for a supported primary ticker and horizon.", response_description="The generated forecast.")
def get_prediction(symbol: str, request: Request, horizon: str = Query(..., description="Forecast horizon.", examples=["daily"])):
    """
    Generate a forecast for a primary ticker.

    Example:
    GET /api/predictions/AAPL?horizon=daily
    """
    client_address = get_client_address(request)

    logger.info(f"Client {client_address} requested a prediction for {symbol} at horizon {horizon}.")

    validate_request(symbol, horizon, tickers, client_address, "predictions")

    try:
        prediction = forecast_service.get_forecast(symbol, horizon)
    except Exception as ex:
        logger.error(ex)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to generate a prediction for '{symbol}'.") from ex

    logger.success(f"Client {client_address} received a prediction for {symbol} at horizon {horizon}: {prediction}.")

    return prediction