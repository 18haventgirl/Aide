"""Create only isolated synthetic health facts for browser acceptance."""
import argparse
from datetime import date, datetime, timedelta
import json
from pathlib import Path

from core.database_core import DatabaseClient
from core.database_core.config import DatabaseConfig
from service.services.health_record_service import HealthRecordService


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--reference-date", type=date.fromisoformat, required=True)
    args = parser.parse_args()
    root = args.directory.resolve()
    root.mkdir(parents=True, exist_ok=True)
    config = DatabaseConfig()
    config.db_type = "sqlite"
    config.sqlite_path = str(root / "aide.sqlite")
    database = DatabaseClient(config)
    if not database.initialize() or not database.create_tables():
        raise RuntimeError("demo database initialization failed")
    try:
        service = HealthRecordService(database)
        day = args.reference_date - timedelta(days=1)
        headache = service.create_record(1, observed_at=datetime.combine(day, datetime.min.time()),
            time_precision="day", record_type="symptom", title="功能验收：头痛记录",
            summary="合成数据：昨天轻微头痛，用于验证日历、更正和跨会话读取。",
            details={"body_site": "太阳穴", "severity": 2}, source="manual", confidence="user_confirmed",
            idempotency_key=f"demo-headache-{args.reference_date}")
        medication = service.create_record(1, observed_at=datetime.combine(day, datetime.min.time()).replace(hour=20),
            time_precision="minute", record_type="medication", title="功能验收：用药事实",
            summary="合成数据：记录服用布洛芬这一事实，不提供剂量或用药建议。",
            details={"medication_name": "布洛芬"}, source="manual", confidence="user_confirmed",
            idempotency_key=f"demo-medication-{args.reference_date}")
        report = {"scope": "synthetic_isolated_database", "database": str(root / "aide.sqlite"),
                  "reference_date": args.reference_date.isoformat(), "headache_id": headache.id,
                  "medication_id": medication.id, "event_date": day.isoformat()}
        (root / "fixture.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False))
    finally:
        database.close()


if __name__ == "__main__":
    main()
