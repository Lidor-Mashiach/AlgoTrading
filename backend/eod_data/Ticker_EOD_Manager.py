import yfinance as yf
import pandas as pd
from  eod_data.Ticker_EOD_Extractor import Ticker_EOD_Extractor

class Tickers_EOD_Manager:
    def __init__(self, tickers_list, supporting_tickers_list, periods=[20, 50, 100, 150, 200]):
        self.tickers_list = tickers_list
        self.supporting_tickers_list = supporting_tickers_list
        self.periods = periods

    def extract_all_tickers_data(self, ticker_sync_status: dict[str, dict] = None) -> dict[str, tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]]:
        tickers_data = self.fetch_daily_tickers_data(ticker_sync_status)

        supporting_tickers_data = {k: v for k, v in tickers_data.items() if k in self.supporting_tickers_list}
                
        all_data = {}
        for ticker in self.tickers_list:
            extractor = Ticker_EOD_Extractor(ticker, tickers_data[ticker], supporting_tickers_data, periods=self.periods)
            ticker_data = extractor.extract_ticker_data(ticker_sync_status[ticker]['db_latest'])
            ticker_data_daily, ticker_data_weekly, ticker_data_monthly = self.split_by_horizon(ticker_data)
            all_data[ticker] = ticker_data_daily, ticker_data_weekly, ticker_data_monthly
            
        return all_data
    
    def fetch_daily_tickers_data(self, tickers_status: dict[str, dict]) -> dict[str, pd.DataFrame]:
        tickers = list(tickers_status.keys())

        raw_df = yf.download(tickers, start="1990-01-01", interval="1d", auto_adjust=False, progress=False)
        raw_df.index = raw_df.index.strftime("%Y-%m-%d")

        if len(tickers) == 1:
            ticker = tickers[0]
            yf_latest = tickers_status[ticker]["yf_latest"]

            raw_df.columns = raw_df.columns.get_level_values(0)
            raw_df = raw_df[raw_df.index <= yf_latest]
            return {ticker: raw_df.dropna(subset=["Close"])}

        ticker_dfs = {}

        for ticker in tickers:
            yf_latest = tickers_status[ticker]["yf_latest"]

            ticker_df = raw_df.xs(ticker, axis=1, level=1)
            ticker_df = ticker_df[ticker_df.index <= yf_latest]

            ticker_dfs[ticker] = ticker_df.dropna(subset=["Close"])

        return ticker_dfs
    
    def split_by_horizon(self, df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        daily_cols   = [col for col in df.columns if "daily"   in col or "prev_day" in col]
        weekly_cols  = [col for col in df.columns if "weekly"  in col or "week" in col]
        monthly_cols = [col for col in df.columns if "monthly" in col or "month" in col]

        daily_df = df[daily_cols]
        weekly_df = df[weekly_cols]
        monthly_df = df[monthly_cols]

        split_column_count = (
            daily_df.shape[1]
            + weekly_df.shape[1]
            + monthly_df.shape[1]
        )

        if split_column_count != df.shape[1]:
            raise ValueError(
                f"Column count mismatch: original has {df.shape[1]} columns, "
                f"split DataFrames have {split_column_count} columns."
            )
        
        return df[daily_cols], df[weekly_cols], df[monthly_cols]