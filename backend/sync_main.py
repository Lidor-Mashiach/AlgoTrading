from eod_data.Ticker_EOD_Manager import Tickers_EOD_Manager
from storage.TickersDBManager import TickersDBManager

from sync.SyncManager import SyncManager
from sync.SyncStatus import SyncStatus

from utils.ConfigLoader import ConfigLoader
from utils.ConsoleLogger import ConsoleLogger

import pandas as pd

import threading

from datetime import datetime, timedelta
import time

from ai_bridge import train_service

logger = ConsoleLogger("sync_main")

def init_managers(tickers, supporting_tickers, currencies, periods, db_name):
    logger.section("Initializing Managers")

    db_manager = TickersDBManager(db_name, tickers + supporting_tickers + currencies, supporting_tickers, periods)
    sync_manager = SyncManager(tickers + supporting_tickers + currencies, db_manager)

    logger.success("Database manager initialized")
    logger.success("Sync manager initialized")

    return db_manager, sync_manager


def get_sync_lists(sync_manager):
    logger.section("Checking Sync Status")

    ticker_sync_status = sync_manager.get_sync_status()

    synced_tickers = [
        ticker for ticker, status in ticker_sync_status.items()
        if status["is_synced"]
    ]

    unsynced_tickers = [
        ticker for ticker, status in ticker_sync_status.items()
        if not status["is_synced"]
    ]

    logger.info(f"Synced tickers: {len(synced_tickers)}")
    logger.info(f"Unsynced tickers: {len(unsynced_tickers)}")

    if synced_tickers:
        logger.success(f"Already synced: {', '.join(synced_tickers)}")

    if unsynced_tickers:
        logger.warning(f"Need syncing: {', '.join(unsynced_tickers)}")

    return ticker_sync_status, synced_tickers, unsynced_tickers


def sync_unsynced_tickers(db_manager, unsynced_tickers, ticker_sync_status):
    logger.section("Fetching EOD Data")

    eod_manager = Tickers_EOD_Manager(unsynced_tickers, db_manager.get_supporting_tickers(), periods=db_manager.get_periods())
    all_data = eod_manager.extract_all_tickers_data(ticker_sync_status)

    logger.success("Finished fetching data")

    for ticker in unsynced_tickers:
        logger.subsection(f"Syncing {ticker}")

        daily_df, weekly_df, monthly_df = all_data[ticker]
        full_df = pd.concat([daily_df, weekly_df, monthly_df], axis=1)

        logger.info(f"New rows fetched: daily={len(daily_df)}, "
                    f"weekly={len(weekly_df)}, monthly={len(monthly_df)}")

        ticker_db = db_manager.get_ticker(ticker)
        ticker_db.add_dataframe(full_df)

        # Total rows in the store after the append, so the log shows the full
        # picture and not just this run's delta.
        total_daily = len(ticker_db.get_data_as_pd("daily"))
        logger.info(f"Total rows in store: {total_daily}")

        logger.success(f"{ticker} synced successfully")

def refresh_model():
    def _run_refresh():
        """Background worker: refresh features and retrain what a new candle needs.
        Runs only AFTER the sync has finished (see run_sync_cycle), so it always works
        on up-to-date data. It reads the already-synced DB, rebuilds features, and
        retrains - or, on a fresh machine with no models, runs the full pipeline once.
        train_if_needed guards itself with a file lock, so overlapping refreshes are
        safe. Logs the result when done."""
        try:
            result = train_service.train_if_needed()
            logger.info(f"Model refresh completed with result: {result}")
        except Exception as exc:
            logger.error(f"Model refresh failed: {exc}")

    logger.section("Starting Model Refresh")

    # Fire the retrain on a background thread and return IMMEDIATELY, so the main
    # loop is never blocked - the system keeps flowing. The sync already ran before
    # this (run_sync_cycle), so the data is current; only the training runs here.
    # While it runs, the models on disk are not yet updated, so
    # ai/utils/model_status.is_ready() reports False and get_forecast returns
    # "training"/"busy" - the GUI shows a please-wait screen and polls again until
    # ready. A daemon thread completes as long as the 24/7 process is alive.
    threading.Thread(target=_run_refresh, daemon=True).start()

    logger.info("Model refresh started in the background "
                "(poll ai/utils/model_status.is_ready() for readiness)")


def close_db(db_manager):
    logger.section("Closing Database Connection")

    db_manager.close()

    logger.success("Database connection closed successfully")


def seconds_until_next_sync(hour=14, minute=0):
    now = datetime.now()
    next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

    if next_run <= now:
        next_run += timedelta(days=1)

    return (next_run - now).total_seconds()


def run_sync_cycle(sync_manager, db_manager):
    ticker_sync_status, _ , unsynced_tickers = get_sync_lists(sync_manager)

    if unsynced_tickers:
        SyncStatus.set_syncing()
        sync_unsynced_tickers(db_manager, unsynced_tickers, ticker_sync_status)
        SyncStatus.set_finished()
    else:
        logger.success("All tickers are already synced. No update needed.")

        # Always hand off to the training bridge. It is the single place that decides
        # what needs doing: build every model on a fresh machine, retrain a horizon
        # whose candle just closed, or do nothing. Skipping it when the data happened
        # to be synced would leave a machine with no models stuck reporting "training"
        # forever.
    refresh_model()

def sync_scheduler(sync_manager, db_manager, sync_time):
    while True:
        seconds_until_next = seconds_until_next_sync(
            sync_time["hour"],
            sync_time["minute"]
        )

        logger.info(
            f"Next sync scheduled in {int(seconds_until_next) // 3600} hours, "
            f"{(int(seconds_until_next) % 3600) // 60} minutes, and "
            f"{int(seconds_until_next) % 60} seconds"
        )

        time.sleep(seconds_until_next)

        run_sync_cycle(sync_manager, db_manager)


def main():
    logger.section("Loading Configuration")
    tickers, supporting_tickers, currencies ,horizons, periods, db_name, sync_time = ConfigLoader.load_prediction_settings()

    logger.info(f"Database name: {db_name}")
    logger.info(f"Tickers: {', '.join(tickers)}")
    logger.info(f"Supporting Tickers: {', '.join(supporting_tickers)}")
    logger.info(f"Currencies: {', '.join(currencies)}")
    logger.info(f"Horizons: {', '.join(horizons)}")
    logger.info(f"Periods: {', '.join(map(str, periods))}")
    logger.info(f"Sync time: {(sync_time['hour'] % 12) or 12:02d}:{sync_time['minute']:02d} {'AM' if sync_time['hour'] < 12 else 'PM'}")

    db_manager, sync_manager = init_managers(tickers, supporting_tickers, currencies, periods, db_name)

    run_sync_cycle(sync_manager, db_manager)

    logger.section("Starting Scheduled Sync")
    # Run the scheduler on the MAIN thread so this process stays alive 24/7.
    # If main() returned here, Python would exit and instantly kill every daemon
    # thread - including the background model refresh. That is why no training
    # ever ran: the thread was killed a millisecond after it started.
    sync_scheduler(sync_manager, db_manager, sync_time)


if __name__ == "__main__":
    main()