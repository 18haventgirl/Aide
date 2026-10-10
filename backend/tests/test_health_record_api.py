"""Real ASGI routing + SQLite, with only authentication/service dependencies replaced."""
from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from api.health_record_api import health_record_router
from core.auth_core import get_current_user
from core.database_core import DatabaseClient
from core.database_core.config import DatabaseConfig
from service.services.health_record_service import HealthRecordService
from service.models.health_record import HealthRecord


class HealthApiTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        config = DatabaseConfig()
        config.db_type = "sqlite"
        config.sqlite_path = str(Path(self.directory.name) / "health.sqlite")
        self.db = DatabaseClient(config)
        self.db.initialize()
        self.db.create_tables()
        self.service = HealthRecordService(self.db)
        app = FastAPI()
        app.include_router(health_record_router, prefix="/api")
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "1"}
        self.client = TestClient(app, raise_server_exceptions=False)
        self.patcher = patch("api.health_record_api._service", return_value=self.service)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        self.client.close()
        self.db.close()
        self.directory.cleanup()

    def test_retry_conflict_timezone_and_owner(self):
        payload = {"observed_at": "2026-01-01T18:30:00Z", "title": "合成记录", "idempotency_key": "api-retry"}
        first = self.client.post("/api/health-records/1", json=payload)
        repeat = self.client.post("/api/health-records/1", json=payload)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(repeat.status_code, 200)
        record = first.json()["data"]
        self.assertEqual(record["id"], repeat.json()["data"]["id"])
        self.assertEqual(record["observed_at"], "2026-01-02T02:30:00")
        self.assertEqual(self.client.post("/api/health-records/1", json={**payload, "title": "不同事实"}).status_code, 409)
        self.assertEqual(self.client.post("/api/health-records/2", json=payload).status_code, 403)
        self.assertEqual(self.client.get("/api/health-records/2").status_code, 403)
        self.assertEqual(len(self.service.list_records(1)), 1)

    def test_null_date_patch_does_not_move_record_to_today(self):
        record = self.service.create_record(1, observed_at=datetime(2026, 1, 1),
            time_precision="day", record_type="symptom", title="合成记录")
        response = self.client.patch(f"/api/health-records/1/{record.id}", json={"observed_at": None})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.service.get_record(1, record.id).observed_at, datetime(2026, 1, 1))

    def test_storage_failure_returns_error_not_empty_success(self):
        with patch.object(self.service, "record_page", side_effect=RuntimeError("synthetic offline")):
            response = self.client.get("/api/health-records/1")
        self.assertEqual(response.status_code, 500)

    def test_revision_conflict_and_history_authorization(self):
        record = self.service.create_record(1, observed_at=datetime(2026, 1, 1),
            time_precision="day", record_type="symptom", title="合成记录")
        route = f"/api/health-records/1/{record.id}"
        updated = self.client.patch(route, json={"summary": "更正", "expected_revision": 1})
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["data"]["revision"], 2)
        stale = self.client.patch(route, json={"summary": "旧版本", "expected_revision": 1})
        self.assertEqual(stale.status_code, 409)
        history = self.client.get(route + "/history").json()["data"]["history"]
        self.assertEqual(len(history), 2)
        self.assertEqual(self.client.get(f"/api/health-records/2/{record.id}/history").status_code, 403)

    def test_calendar_counts_all_records_and_day_pages_do_not_overlap(self):
        with self.db.get_session() as session:
            session.add_all([HealthRecord(user_id=1, observed_at=datetime(2026, 10, 7),
                time_precision="day", record_type="symptom", title=f"合成旧记录{i}", status="active") for i in range(503)])
            session.add(HealthRecord(user_id=2, observed_at=datetime(2026, 10, 7),
                time_precision="day", record_type="symptom", title="他人记录", status="active"))
            session.add(HealthRecord(user_id=1, observed_at=datetime(2026, 10, 7),
                time_precision="day", record_type="symptom", title="删除记录", status="deleted"))
            session.commit()
        calendar = self.client.get("/api/health-records/1/calendar", params={"month": "2026-10"})
        self.assertEqual(calendar.status_code, 200)
        self.assertEqual(calendar.json()["data"]["daily_counts"], {"2026-10-07": 503})
        first = self.client.get("/api/health-records/1", params={"start_date": "2026-10-07", "end_date": "2026-10-07", "limit": 2}).json()["data"]
        second = self.client.get("/api/health-records/1", params={"start_date": "2026-10-07", "end_date": "2026-10-07", "limit": 2, "offset": 2}).json()["data"]
        self.assertEqual(first["total"], 503)
        self.assertEqual(first["returned"], 2)
        self.assertTrue(first["has_more"])
        self.assertFalse({r["id"] for r in first["records"]}.intersection(r["id"] for r in second["records"]))
        self.assertEqual(self.client.get("/api/health-records/2/calendar", params={"month": "2026-10"}).status_code, 403)
        self.assertEqual(self.client.get("/api/health-records/1/calendar", params={"month": "2026-13"}).status_code, 422)

    def test_manual_api_cannot_forge_conversation_or_time_metadata(self):
        for extra in ({"source": "conversation"}, {"source_message_id": "999"}, {"details": {"_time": {"expression": "伪造"}}}):
            response = self.client.post("/api/health-records/1", json={"title": "合成记录", **extra})
            self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
