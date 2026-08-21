from storage.TickerDB import TickerDB


class TickersDBManager:
    def __init__(self, db_name: str, tickers: list[str], supporting_tickers: list[str], periods: list[int]):
        self.db_name = db_name
        self.tickers = tickers

        self.supporting_tickers = supporting_tickers
        self.periods = periods

        self.ticker_dbs = {ticker: TickerDB(db_name, ticker, periods) for ticker in tickers}

    def get_ticker(self, ticker: str) -> TickerDB:
        ticker = ticker.upper()
        if ticker not in self.ticker_dbs:
            raise ValueError(f"Unknown ticker '{ticker}'. Available: {list(self.ticker_dbs.keys())}")
        return self.ticker_dbs[ticker]

    def add_dataframe(self, ticker: str, df):
        self.get_ticker(ticker).add_dataframe(df)

    def get_data_as_pd(self, ticker: str, horizon: str, start_date: str = None, limit: int = None):
        return self.get_ticker(ticker).get_data_as_pd(horizon, start_date, limit)

    def get_data_as_dict(self, ticker: str, horizon: str, start_date: str = None, limit: int = None):
        return self.get_ticker(ticker).get_data_as_dict(horizon, start_date, limit)

    def get_data_as_eod(self, ticker: str, horizon: str, start_date: str = None, limit: int = None):
        return self.get_ticker(ticker).get_data_as_eod(horizon, start_date, limit)

    def get_supporting_tickers(self) -> list[str]:
        return self.supporting_tickers

    def get_periods(self) -> list[int]:
        return self.periods




