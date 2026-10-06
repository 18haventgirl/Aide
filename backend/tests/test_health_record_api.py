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
        with patch.object(self.service, "list_records", side_effect=RuntimeError("synthetic offline")):
            response = self.client.get("/api/health-records/1")
        self.assertEqual(response.status_code, 500)


if __name__ == "__main__":
    unittest.main()
