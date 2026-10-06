"""Back up existing SQLite before adding health retry receipts; never rewrite facts."""
from datetime import datetime
import json
from pathlib import Path
import sqlite3

from dotenv import load_dotenv
from sqlalchemy import inspect
from sqlalchemy import text
from core.database_core import DatabaseClient
from ..models.health_record import HealthRecord
from ..models.health_record_receipt import HealthRecordReceipt
from ..models.health_record_revision import HealthRecordVersion, HealthRecordRevision


def prepare(database, backup_directory):
    if database.engine.dialect.name != "sqlite":
        raise ValueError("this local migration command supports SQLite only")
    names = set(inspect(database.engine).get_table_names())
    if "health_records" not in names:
        raise ValueError("initialize the base health_records table first")
    required = {"health_record_receipts", "health_record_versions", "health_record_revisions"}
    if required.issubset(names):
        return {"status": "already_prepared", "backup": None}
    path = Path(database.engine.url.database).resolve()
    backup_directory.mkdir(parents=True, exist_ok=True)
    backup = backup_directory / ("health-before-receipts-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".sqlite")
    with sqlite3.connect(str(path)) as source, sqlite3.connect(str(backup)) as target:
        source.backup(target)
        if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("backup integrity check failed")
    HealthRecordReceipt.__table__.create(database.engine, checkfirst=True)
    HealthRecordVersion.__table__.create(database.engine, checkfirst=True)
    HealthRecordRevision.__table__.create(database.engine, checkfirst=True)
    with database.engine.begin() as connection:
        connection.execute(text("INSERT INTO health_record_versions (record_id,user_id,revision,created_at,updated_at) SELECT h.id,h.user_id,1,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP FROM health_records h WHERE NOT EXISTS (SELECT 1 FROM health_record_versions v WHERE v.record_id=h.id)"))
    return {"status": "prepared", "backup": str(backup)}


def main():
    backend = Path(__file__).resolve().parents[2]
    load_dotenv(backend / ".env")
    database = DatabaseClient()
    if not database.initialize():
        raise RuntimeError("database unavailable")
    try:
        print(json.dumps(prepare(database, backend / "data" / "backups"), ensure_ascii=False))
    finally:
        database.close()


if __name__ == "__main__":
    main()
