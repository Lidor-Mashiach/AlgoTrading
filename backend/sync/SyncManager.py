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

    
    def exchange_today(self, ticker: str):
        """
        Today's date on the exchange's own clock.

        Tel Aviv, Frankfurt and New York are not on the same calendar date at any given
        moment, so "today" has to be asked of each exchange rather than read off this
        machine. pandas carries its own timezone database, so no extra package is needed.
        """
        try:
            zone = yf.Ticker(ticker).info.get("exchangeTimezoneName")
            if zone:
                return pd.Timestamp.now(tz=zone).date()
        except Exception:
            pass

        # Yahoo gave no timezone. The local clock is a worse answer than the exchange's
        # own, and a far better one than guessing.
        return pd.Timestamp.now().date()

    def previous_closed_trading_date(self, ticker: str):
        """
        The most recent trading day that has finished.

        Decided by comparing dates, not by reading marketState.

        marketState describes the market right now and says nothing about which day the
        last row belongs to, so a rule built on it drops whatever happens to sit at the
        end of the frame. Before the opening bell Yahoo has not written a row for today
        yet, and that rule then discarded the previous day: a session that had closed
        hours earlier. Comparing dates cannot make that mistake, because it looks at
        what it is about to drop.
        """
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

        # Keep every row dated before today and take the newest of them. A row dated
        # today may still be open. Selecting by date rather than by position means the
        # answer cannot depend on how many rows Yahoo happened to return, or on whether
        # it has written one for today yet.
        finished = df.index[df.index.date < self.exchange_today(ticker)]

        if len(finished) == 0:
            return None

        return str(finished[-1].date())

    
    def is_synced(self, yf_latest, db_latest) -> bool:
        if yf_latest is None or db_latest is None:
            return False
        
        return yf_latest == db_latest