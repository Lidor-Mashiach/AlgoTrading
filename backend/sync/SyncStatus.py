import json
from pathlib import Path
from datetime import datetime

class SyncStatus:
    STATUS_FILE = Path(__file__).resolve().parents[1] / "sync_status.json"

    KEY_IS_SYNCING = "is_syncing"
    KEY_STARTED_AT = "started_at"
    KEY_FINISHED_AT = "finished_at"

    @staticmethod
    def set_syncing():
        SyncStatus.STATUS_FILE.write_text(
            json.dumps(
                {
                    SyncStatus.KEY_IS_SYNCING: True,
                    SyncStatus.KEY_STARTED_AT: datetime.now().isoformat(),
                    SyncStatus.KEY_FINISHED_AT: None,
                },
                indent=2
            ),
            encoding="utf-8"
        )

    @staticmethod
    def set_finished():
        SyncStatus.STATUS_FILE.write_text(
            json.dumps(
                {
                    SyncStatus.KEY_IS_SYNCING: False,
                    SyncStatus.KEY_STARTED_AT: None,
                    SyncStatus.KEY_FINISHED_AT: datetime.now().isoformat(),
                },
                indent=2
            ),
            encoding="utf-8"
        )

    @staticmethod
    def is_syncing():
        if not SyncStatus.STATUS_FILE.exists():
            return False

        data = json.loads(SyncStatus.STATUS_FILE.read_text(encoding="utf-8"))
        return data.get(SyncStatus.KEY_IS_SYNCING, False)