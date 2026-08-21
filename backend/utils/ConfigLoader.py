import json
from pathlib import Path


class ConfigLoader:
    CONFIG_FILENAME = "config.json"
    CONFIG_PATH = Path(__file__).parent.parent / CONFIG_FILENAME

    KEY_PREDICTION_SETTINGS = "prediction_settings"
    KEY_REST_API_SETTINGS = "rest_api_settings"

    KEY_TICKERS = "tickers"
    KEY_SUPPORTING_TICKERS = "supporting_tickers"
    KEY_CURRENCIES = "currencies"
    KEY_HORIZONS = "horizons"
    KEY_PERIODS = "periods"
    KEY_DB_NAME = "db_name"

    KEY_HOST = "host"
    KEY_PORT = "port"

    @staticmethod
    def load_prediction_settings():
        with open(ConfigLoader.CONFIG_PATH, "r", encoding="utf-8") as file:
            config = json.load(file)

        db_path = str(
            ConfigLoader.CONFIG_PATH.parent.parent / config[ConfigLoader.KEY_PREDICTION_SETTINGS][ConfigLoader.KEY_DB_NAME]
        )

        return (
            config[ConfigLoader.KEY_PREDICTION_SETTINGS][ConfigLoader.KEY_TICKERS],
            config[ConfigLoader.KEY_PREDICTION_SETTINGS][ConfigLoader.KEY_SUPPORTING_TICKERS],
            config[ConfigLoader.KEY_PREDICTION_SETTINGS][ConfigLoader.KEY_CURRENCIES],
            config[ConfigLoader.KEY_PREDICTION_SETTINGS][ConfigLoader.KEY_HORIZONS],
            config[ConfigLoader.KEY_PREDICTION_SETTINGS][ConfigLoader.KEY_PERIODS],
            db_path,
        )

    @staticmethod
    def load_rest_settings():
        with open(ConfigLoader.CONFIG_PATH, "r", encoding="utf-8") as file:
            config = json.load(file)

        return (
            config[ConfigLoader.KEY_REST_API_SETTINGS][ConfigLoader.KEY_HOST],
            config[ConfigLoader.KEY_REST_API_SETTINGS][ConfigLoader.KEY_PORT]
        )