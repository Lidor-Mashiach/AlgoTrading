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


def get_sync_lists(sync_manager, verbose=True):
    if verbose:
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

    # An hourly check that finds nothing new is the normal case, and printing a block
    # every hour for it would bury the entries that matter.
    if verbose or unsynced_tickers:
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
            logger.refresh(f"Model refresh completed with result: {result}")
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


# How long to wait between checks. Hourly, not once a day.
#
# A fixed daily time cannot work, because the thing being waited for is not a clock. Yahoo
# publishes a session when it publishes it, and the delay is different for every exchange:
# a check has found Tel Aviv and Frankfurt still missing a session ten hours after both
# had closed. A daily check that lands during one of those gaps leaves the whole system a
# day behind until the next one, which is a full day later.
#
# Checking every hour bounds that gap at an hour. Each ticker is still judged against its
# own exchange clock inside previous_closed_trading_date, so an hourly check is not a
# blunt instrument: it is simply asking often enough that whichever exchange publishes
# next is picked up promptly.
SYNC_INTERVAL_SECONDS = 60 * 60


def seconds_until_next_sync(hour=None, minute=None):
    """Kept for callers that still pass a time of day. The interval is fixed now."""
    return SYNC_INTERVAL_SECONDS


def run_sync_cycle(sync_manager, db_manager, verbose=True, hold_clients=False):
    """
    Bring the store up to date.

    hold_clients decides what a client sees while this runs. At startup it is True, so
    the API reports itself unavailable for the whole cycle and the interface holds a
    waiting screen. That matters because deciding what needs fetching means asking Yahoo
    about every symbol, which takes time, and during it the store still holds yesterday.
    Without the hold, the interface would come up, render that stale day, and only
    correct itself later, which is exactly what it used to do.

    On the hourly cycles it is False. There the store is already current and almost every
    cycle finds nothing, so blocking a working screen for a routine check would be worse
    than the problem. If one of those cycles does find something, the fetch itself still
    holds clients, as it always did.
    """
    logger.section("=" * 62)
    logger.info("")
    logger.info("Sync check starting")
    logger.info("")
    logger.section("=" * 62)

    if hold_clients:
        SyncStatus.set_syncing()

    updated = []
    try:
        ticker_sync_status, _ , unsynced_tickers = get_sync_lists(sync_manager, verbose)

        if unsynced_tickers:
            SyncStatus.set_syncing()
            sync_unsynced_tickers(db_manager, unsynced_tickers, ticker_sync_status)
            updated = unsynced_tickers
    finally:
        # Released whatever happened. A cycle that raised must not leave every endpoint
        # answering "unavailable" for the life of the process.
        SyncStatus.set_finished()

    logger.section_end("=" * 62)
    logger.info("")
    if updated:
        logger.success(f"Sync complete: {len(updated)} ticker(s) updated")
        for ticker in updated:
            logger.info(f"    {ticker}")
    else:
        logger.info("Sync complete: no change, every ticker was already current")
    logger.info("")
    logger.section_end("=" * 62)

    return updated


def sync_scheduler(sync_manager, db_manager, sync_time=None):
    # The clock starts when the system does. A machine switched on at 14:20 checks at
    # 15:20, not at some fixed hour it may never be running for.
    logger.info(f"Checking every {SYNC_INTERVAL_SECONDS // 60} minutes for newly published sessions")

    while True:
        time.sleep(SYNC_INTERVAL_SECONDS)

        # Retrain only when a candle actually arrived.
        #
        # The bridge decides for itself whether anything needs training, but it reaches
        # that decision by rebuilding features and splitting the data first, which is
        # several seconds of work and a screen of output. Running it hourly against a
        # store that has not moved produced all of that to conclude nothing had changed.
        # Startup still calls it unconditionally, so a machine with no models is covered.
        if run_sync_cycle(sync_manager, db_manager, verbose=False):
            refresh_model()


def main():
    logger.section("Loading Configuration")
    tickers, supporting_tickers, currencies ,horizons, periods, db_name, sync_time = ConfigLoader.load_prediction_settings()

    logger.info(f"Database name: {db_name}")
    logger.info(f"Tickers: {', '.join(tickers)}")
    logger.info(f"Supporting Tickers: {', '.join(supporting_tickers)}")
    logger.info(f"Currencies: {', '.join(currencies)}")
    logger.info(f"Horizons: {', '.join(horizons)}")
    logger.info(f"Periods: {', '.join(map(str, periods))}")
    logger.info(f"Sync interval: every {SYNC_INTERVAL_SECONDS // 60} minutes, plus once at startup")

    db_manager, sync_manager = init_managers(tickers, supporting_tickers, currencies, periods, db_name)

    # Startup holds clients until the store is current, so the interface can never open
    # on a stale day.
    run_sync_cycle(sync_manager, db_manager, hold_clients=True)

    # Always on startup. The training bridge is the single place that decides what needs
    # doing, and a machine whose models are missing has to reach it even when the store
    # was already current.
    refresh_model()

    logger.section("Starting Scheduled Sync")
    # Run the scheduler on the MAIN thread so this process stays alive 24/7.
    # If main() returned here, Python would exit and instantly kill every daemon
    # thread - including the background model refresh. That is why no training
    # ever ran: the thread was killed a millisecond after it started.
    sync_scheduler(sync_manager, db_manager, sync_time)


if __name__ == "__main__":
    main()