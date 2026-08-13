import yfinance as yf
import pandas as pd
from storage.TickersDBManager import TickersDBManager

class SyncManager:
    def __init__(self, tickers: list[str], ticker_db_manager: TickersDBManager):
        self.tickers = tickers
        self.ticker_db_manager = ticker_db_manager

    def get_sync_status(self) -> dict:
        sync_status = {}
        for ticker in self.tickers:
            yf_latest = self.previous_closed_trading_date(ticker)
            db_latest_daily = self.ticker_db_manager.get_ticker(ticker).get_latest_date()["daily"]
            sync_status[ticker] = {
                "yf_latest": yf_latest,
                "db_latest": db_latest_daily,
                "is_synced": self.is_synced(yf_latest, db_latest_daily)
            }

        return sync_status

    def get_ticker_state(self, ticker: str):
        info = yf.Ticker(ticker).info
        return info.get("marketState", "UNKNOWN")

    
    def previous_closed_trading_date(self, ticker: str):
        df = yf.download(
            ticker,
            period="10d",
            interval="1d",
            progress=False,
            auto_adjust=False
        )

        if df.empty:
            return None

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        df = df.dropna(subset=["Close"])

        if len(df) < 1:
            return None

        index = -1 if self.get_ticker_state(ticker).upper() in ["CLOSE", "CLOSED"] else -2

        previous_date = str(df.index[index].date())
        return previous_date
    
    def is_synced(self, yf_latest, db_latest) -> bool:
        if yf_latest is None or db_latest is None:
            return False
        
        return yf_latest == db_latest