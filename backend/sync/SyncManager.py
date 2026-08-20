import yfinance as yf
import pandas as pd
from storage.TickersDBManager import TickersDBManager


class SyncManager:
    def __init__(self, tickers: list[str], ticker_db_manager: TickersDBManager):
        self.tickers = tickers
        self.ticker_db_manager = ticker_db_manager

        # An exchange does not move between timezones, so its zone is asked for once and
        # kept for the life of the process.
        self._zones: dict[str, str] = {}

        # One Yahoo profile per ticker per cycle, shared by everything that needs it.
        # The profile carries both the timezone and the market state, and fetching it is
        # the slowest thing in a status check by a wide margin. Asking for it twice per
        # ticker, once for each field, doubled the wait for no reason.
        self._info: dict[str, dict] = {}

    def get_sync_status(self) -> dict:
        """
        Where every ticker stands, from a single download.

        Asking Yahoo once per ticker meant fourteen round trips before the system could
        decide whether it had anything to do at all, and that ran to more than twenty
        seconds on every startup. The startup now holds the interface behind a waiting
        screen for as long as this takes, so those seconds became visible: a system with
        nothing to fetch still sat blank while it worked that out. One download for all
        of them answers the same question in a fraction of the time.
        """
        # Profiles are per cycle: the timezone never changes but the market state does,
        # so the cache is emptied at the start of each check rather than kept.
        self._info = {}

        frames = self.download_recent(self.tickers)

        sync_status = {}
        for ticker in self.tickers:
            yf_latest = self.last_finished_session(ticker, frames.get(ticker))
            db_latest_daily = self.ticker_db_manager.get_ticker(ticker).get_latest_date()["daily"]
            sync_status[ticker] = {
                "yf_latest": yf_latest,
                "db_latest": db_latest_daily,
                "is_synced": self.is_synced(yf_latest, db_latest_daily)
            }

        return sync_status

    def ticker_info(self, ticker: str) -> dict:
        """The Yahoo profile for a ticker, fetched at most once per cycle."""
        if ticker not in self._info:
            try:
                self._info[ticker] = yf.Ticker(ticker).info or {}
            except Exception:
                self._info[ticker] = {}
        return self._info[ticker]

    def get_ticker_state(self, ticker: str):
        return self.ticker_info(ticker).get("marketState", "UNKNOWN")

    def exchange_today(self, ticker: str):
        """
        Today's date on the exchange's own clock.

        Tel Aviv, Frankfurt and New York are not on the same calendar date at any given
        moment, so "today" has to be asked of each exchange rather than read off this
        machine. pandas carries its own timezone database, so no extra package is needed.
        """
        if ticker not in self._zones:
            self._zones[ticker] = self.ticker_info(ticker).get("exchangeTimezoneName") or ""

        zone = self._zones[ticker]
        if zone:
            try:
                return pd.Timestamp.now(tz=zone).date()
            except Exception:
                pass

        # Yahoo gave no timezone. The local clock is a worse answer than the exchange's
        # own, and a far better one than guessing.
        return pd.Timestamp.now().date()

    def session_has_ended(self, ticker: str) -> bool:
        """
        Has today's session finished on this exchange.

        POST is after hours trading, which begins the moment the closing bell rings, so
        the daily bar is already final there as much as it is in CLOSED.
        """
        return self.get_ticker_state(ticker).upper() in ("POST", "POSTPOST", "CLOSE", "CLOSED")

    def download_recent(self, tickers: list[str]) -> dict:
        """Recent daily bars for many tickers, in one request, split per ticker."""
        raw = yf.download(tickers, period="10d", interval="1d",
                          progress=False, auto_adjust=False, group_by="column")

        frames = {}
        for ticker in tickers:
            try:
                if isinstance(raw.columns, pd.MultiIndex):
                    frame = raw.xs(ticker, axis=1, level=1)
                else:
                    frame = raw
                frames[ticker] = frame.dropna(subset=["Close"])
            except Exception:
                frames[ticker] = None

        return frames

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

        return self.last_finished_session(ticker, df.dropna(subset=["Close"]))

    def last_finished_session(self, ticker: str, df):
        """
        The newest finished session in a frame that has already been fetched.

        Holds the whole rule, so a single download and a bulk one reach the same answer.
        """
        if df is None or len(df) < 1:
            return None

        today = self.exchange_today(ticker)
        dates = df.index.date

        # Rows dated before today have finished by definition.
        finished = df.index[dates < today]

        # A row dated today is finished only once the session has ended, and that is the one
        # thing a date cannot answer. marketState is asked here and nowhere else, about
        # this row alone. It can never cause a completed day to be dropped, because a row
        # dated earlier than today is already in `finished` and is never re-examined.
        #
        # Without this, every exchange spent the hours between its closing bell and its
        # local midnight reporting the session before last. In Israel that is most of the
        # evening for the American market.
        if len(df) and dates[-1] == today and self.session_has_ended(ticker):
            return str(df.index[-1].date())

        if len(finished) == 0:
            return None

        return str(finished[-1].date())

    def is_synced(self, yf_latest, db_latest) -> bool:
        if yf_latest is None or db_latest is None:
            return False

        return yf_latest == db_latest