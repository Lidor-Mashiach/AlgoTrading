import sqlite3
import pandas as pd

from eod_data.Ticker_EOD import Ticker_EOD

class TickerDB:
    def __init__(self, db_name: str, ticker: str, periods: list = [20, 50, 100, 150, 200]):
        self.db_name = db_name
        self.ticker = ticker
        self.periods = periods
        safe_ticker = self.clean_ticker_name(ticker)
        self.daily_table = f"{safe_ticker}_daily"
        self.weekly_table = f"{safe_ticker}_weekly"
        self.monthly_table = f"{safe_ticker}_monthly"

        self.DAILY_COLS = self._build_daily_cols()
        self.WEEKLY_COLS = self._build_weekly_cols()
        self.MONTHLY_COLS = self._build_monthly_cols()

        self.connection = sqlite3.connect(db_name)
        try:
            self.init_tables()
        finally:
            self.connection.close()

    def clean_ticker_name(self, ticker_name: str) -> str:
        replace_char = '_'
        chars_to_replace = {'.': replace_char, '^': '', '-': replace_char, '=': replace_char }
        for c in chars_to_replace.keys():
            ticker_name = ticker_name.replace(c, chars_to_replace[c])
        
        return ticker_name

    @staticmethod
    def _quote_identifier(identifier: str) -> str:
        return '"' + identifier.replace('"', '""') + '"'

    def _period_cols(self, horizon: str) -> list:
        cols = []
        for period in self.periods:
            cols.append(f"sma_{horizon}_{period}")
        for period in self.periods:
            cols.append(f"ema_{horizon}_{period}")
        return cols

    def _support_cols(self, horizon: str) -> list:
        return [
            f"^VIX_{horizon}_last",
            f"^TNX_{horizon}_last",
            f"^IRX_{horizon}_last",
            f"DX-Y.NYB_{horizon}_last",
        ]

    def _build_daily_cols(self) -> list:
        return [
            "close_daily_last", "pct_change_daily_last",
            *self._period_cols("daily"),
            "volume_prev_day", "volume_avg_daily_90",
            "low_prev_day", "high_prev_day",
            "bb_base_daily", "bb_upper_daily", "bb_lower_daily",
            "rsi_daily", "rsi_ma_daily", "rsi_gap_daily",
            *self._support_cols("daily"),
            "macd_daily", "macd_signal_daily", "atr_daily",
            "stoch_k_daily", "stoch_d_daily",
        ]

    def _build_weekly_cols(self) -> list:
        return [
            "close_weekly_last", "pct_change_week_current", "pct_change_week_prev",
            *self._period_cols("weekly"),
            "volume_week_current", "volume_week_prev",
            "low_week_current", "high_week_current", "low_week_prev", "high_week_prev",
            "bb_base_weekly", "bb_upper_weekly", "bb_lower_weekly",
            "rsi_weekly", "rsi_ma_weekly", "rsi_gap_weekly",
            *self._support_cols("weekly"),
            "macd_weekly", "macd_signal_weekly", "atr_weekly",
            "stoch_k_weekly", "stoch_d_weekly",
        ]

    def _build_monthly_cols(self) -> list:
        return [
            "close_monthly_last", "pct_change_month_current", "pct_change_month_prev",
            *self._period_cols("monthly"),
            "volume_month_current", "volume_month_prev",
            "low_month_current", "high_month_current", "low_month_prev", "high_month_prev",
            "bb_base_monthly", "bb_upper_monthly", "bb_lower_monthly",
            "rsi_monthly", "rsi_ma_monthly", "rsi_gap_monthly",
            *self._support_cols("monthly"),
            "macd_monthly", "macd_signal_monthly", "atr_monthly",
            "stoch_k_monthly", "stoch_d_monthly",
        ]

    def init_tables(self):
        for table, cols in [
            (self.daily_table, self.DAILY_COLS),
            (self.weekly_table, self.WEEKLY_COLS),
            (self.monthly_table, self.MONTHLY_COLS),
        ]:
            self._rebuild_table_if_cols_changed(table, cols)
            quoted_table = self._quote_identifier(table)
            col_definitions = ", ".join(f"{self._quote_identifier(col)} REAL" for col in cols)
            cursor = self.connection.cursor()
            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS {quoted_table} (
                    "date" TEXT PRIMARY KEY,
                    {col_definitions}
                )
            """)
        self.connection.commit()

    def _rebuild_table_if_cols_changed(self, table: str, expected_cols: list):
        cursor = self.connection.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
        if cursor.fetchone() is None:
            return

        quoted_table = self._quote_identifier(table)
        cursor.execute(f"PRAGMA table_info({quoted_table})")
        existing_cols = [row[1] for row in cursor.fetchall() if row[1] != "date"]

        if existing_cols != expected_cols:
            print(f"Columns changed for {table} — dropping and rebuilding (existing data lost).")
            cursor.execute(f"DROP TABLE {quoted_table}")
            self.connection.commit()

    def get_data_as_pd(self, horizon: str, start_date: str = None, limit: int = None) -> pd.DataFrame:
        tables = {
            "daily":   self.daily_table,
            "weekly":  self.weekly_table,
            "monthly": self.monthly_table,
        }
        if horizon not in tables:
            raise ValueError(f"Unknown horizon '{horizon}'. Use 'daily', 'weekly', or 'monthly'.")

        connection = sqlite3.connect(self.db_name)

        try:
            query = f"SELECT * FROM {tables[horizon]}"
            params = []

            if start_date:
                query += " WHERE date >= ?"
                params.append(start_date)

            query += " ORDER BY date DESC"

            if limit:
                query += " LIMIT ?"
                params.append(limit)

            df = pd.read_sql_query(
                query,
                connection,
                params=params,
                index_col="date",
            )

            df = df.apply(pd.to_numeric, errors="coerce")

            return df.sort_index()

        finally:
            connection.close()

    def get_data_as_dict(self, horizon: str, start_date: str = None, limit: int = None) -> list[dict]:
        df = self.get_data_as_pd(horizon, start_date, limit)
        return df.reset_index().to_dict(orient="records")

    def get_data_as_eod(self, horizon: str, start_date: str = None, limit: int = None) -> list[Ticker_EOD]:
        df = self.get_data_as_pd(horizon, start_date, limit)
        return [Ticker_EOD(ticker=self.ticker, date=str(date), features=row.to_dict()) for date, row in df.iterrows()]

    def add_row(self, date: str, features: dict, auto_commit: bool = True):
        cursor = self.connection.cursor()
        for table, cols in [
            (self.daily_table, self.DAILY_COLS),
            (self.weekly_table, self.WEEKLY_COLS),
            (self.monthly_table, self.MONTHLY_COLS),
        ]:
            row = {col: features.get(col) for col in cols}
            placeholders = ", ".join("?" for _ in cols)
            quoted_table = self._quote_identifier(table)
            col_names = ", ".join(self._quote_identifier(col) for col in cols)
            cursor.execute(f"""
                INSERT OR REPLACE INTO {quoted_table} ("date", {col_names})
                VALUES (?, {placeholders})
            """, [date] + list(row.values()))
        if auto_commit:
            self.connection.commit()

    def add_dataframe(self, df: pd.DataFrame):
        connection = sqlite3.connect(self.db_name)

        try:
            for table, cols in [
                (self.daily_table,   self.DAILY_COLS),
                (self.weekly_table,  self.WEEKLY_COLS),
                (self.monthly_table, self.MONTHLY_COLS),
            ]:
                available_cols = [col for col in cols if col in df.columns]

                df[available_cols].to_sql(
                    table,
                    connection,
                    if_exists="append",
                    index=True,
                    index_label="date",
                )

            connection.commit()

        except Exception as e:
            connection.rollback()
            print(f"Failed to insert dataframe for ticker {self.ticker}: {e}")
            raise

        finally:
            connection.close()

    def get_latest_date(self) -> dict:
        connection = sqlite3.connect(self.db_name)

        try:
            cursor = connection.cursor()
            latest_dates = {}

            for horizon, table in [
                ("daily",   self.daily_table),
                ("weekly",  self.weekly_table),
                ("monthly", self.monthly_table),
            ]:
                quoted_table = self._quote_identifier(table)
                cursor.execute(f'SELECT MAX("date") FROM {quoted_table}')
                latest_dates[horizon] = cursor.fetchone()[0]

            return latest_dates

        finally:
            self.connection.close()