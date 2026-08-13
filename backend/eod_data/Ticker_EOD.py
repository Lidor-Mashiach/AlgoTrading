import pandas as pd

class Ticker_EOD:
    def __init__(self, ticker: str, date: str, features: dict):
        self.ticker = ticker
        self.date = date
        self.features = features

        self.daily_features = {k: v for k, v in features.items() if "daily" in k or "prev_day" in k}
        self.weekly_features = {k: v for k, v in features.items() if "weekly" in k or "week" in k}
        self.monthly_features = {k: v for k, v in features.items() if "monthly" in k or "month" in k}

    def __repr__(self):
        return f"Ticker_EOD(ticker={self.ticker}, date={self.date}, features={len(self.features)}, nulls={len(self.has_nulls())})"

    def __str__(self):
        return (
            f"Ticker  : {self.ticker}\n"
            f"Date    : {self.date}\n"
            f"Features: {len(self.features)} total | "
            f"{len(self.daily_features)} daily | "
            f"{len(self.weekly_features)} weekly | "
            f"{len(self.monthly_features)} monthly\n"
            f"Nulls   : {len(self.has_nulls())} ({', '.join(self.has_nulls()) or 'none'})"
        )

    def get_feature(self, name: str):
        return self.features.get(name)

    def get_horizon(self, horizon: str) -> dict:
        horizons = {
            "daily": self.daily_features,
            "weekly": self.weekly_features,
            "monthly": self.monthly_features,
        }
        if horizon not in horizons:
            raise ValueError(f"Unknown horizon '{horizon}'. Use 'daily', 'weekly', or 'monthly'.")
        return horizons[horizon]

    def to_dict(self) -> dict:
        return {"ticker": self.ticker, "date": self.date, **self.features}

    def to_series(self) -> pd.Series:
        return pd.Series(self.to_dict())

    def has_nulls(self) -> list[str]:
        return [k for k, v in self.features.items() if pd.isna(v)]

    def is_valid(self) -> bool:
        if self.has_nulls():
            return False
        if not self.features:
            return False
        if any(len(h) == 0 for h in [self.daily_features, self.weekly_features, self.monthly_features]):
            return False
        return True