"""Health dates, ownership and retry safety using disposable SQLite databases."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from core.database_core import DatabaseClient
from core.database_core.config import DatabaseConfig
from service.models.health_record import HealthRecord
from service.models.health_record_receipt import HealthRecordReceipt
from service.models.health_record_revision import HealthRecordVersion, HealthRecordRevision
from service.services.health_record_service import HealthRecordService, HealthRecordConflict
from service.services.health_time import resolve_health_time, HealthTimeClarification


class HealthTimeTests(unittest.TestCase):
    now = datetime(2026, 10, 6, 20, 0)

    def test_yesterday_and_last_week_use_event_day(self):
        yesterday = resolve_health_time(date_text="昨天晚上", reference=self.now)
        self.assertEqual(yesterday.observed_at, datetime(2026, 10, 5))
        self.assertEqual(yesterday.precision, "day")
        self.assertEqual(resolve_health_time(date_text="上周三", reference=self.now).observed_at,
                         datetime(2026, 9, 30))

    def test_precise_clock_and_leap_year(self):
        result = resolve_health_time(date_text="2024年2月29日下午3点半", reference=self.now)
        self.assertEqual(result.observed_at, datetime(2024, 2, 29, 15, 30))
        self.assertEqual(result.precision, "minute")

    def test_timezone_conversion_crosses_date(self):
        result = resolve_health_time("2026-10-05T18:30:00Z", reference=self.now)
        self.assertEqual(result.observed_at, datetime(2026, 10, 6, 2, 30))
        self.assertEqual(result.precision, "minute")
        unknown = resolve_health_time(reference=datetime(2026, 10, 5, 18, tzinfo=timezone.utc))
        self.assertEqual(unknown.observed_at, datetime(2026, 10, 6, 2))
        self.assertEqual(unknown.confidence, "inferred_time")

    def test_cross_year_yesterday(self):
        result = resolve_health_time(date_text="昨天", reference=datetime(2026, 1, 1, 12))
        self.assertEqual(result.observed_at, datetime(2025, 12, 31))

    def test_ambiguous_invalid_conflicting_future_need_clarification(self):
        examples = [("", "20号", "ambiguous_date"), ("", "9月20日", "ambiguous_date"),
                    ("", "2025年2月29日", "invalid_date"), ("", "昨天和今天", "multiple_dates"),
                    ("2026-10-06T08:00:00", "昨天", "date_conflict"),
                    ("", "明天", "future_event"), ("", "15:00", "missing_date"),
                    ("", "昨天25点", "invalid_clock"), ("", "上周", "unsupported_relative_date")]
        for value, text, reason in examples:
            with self.subTest(text=text), self.assertRaises(HealthTimeClarification) as caught:
                resolve_health_time(value, text, reference=self.now)
            self.assertEqual(caught.exception.reason, reason)

    def test_iso_date_does_not_claim_precise_midnight(self):
        result = resolve_health_time("2026-10-05", reference=self.now)
        self.assertEqual(result.precision, "day")


class HealthMemoryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        config = DatabaseConfig()
        config.db_type = "sqlite"
        config.sqlite_path = str(Path(self.directory.name) / "health.sqlite")
        self.db = DatabaseClient(config)
        self.assertTrue(self.db.initialize())
        self.assertTrue(self.db.create_tables())
        self.service = HealthRecordService(self.db)
        self.facts = dict(observed_at=datetime(2026, 1, 1, 8), time_precision="minute",
                          record_type="symptom", title="合成头痛记录", summary="合成测试",
                          details={"body_site": "头部"})

    def tearDown(self):
        self.db.close()
        self.directory.cleanup()

    def count(self):
        with self.db.get_session() as session:
            return session.query(HealthRecord).count(), session.query(HealthRecordReceipt).count()

    def test_retry_same_key_returns_same_record_and_conflict_is_explicit(self):
        first = self.service.create_record(1, **self.facts, idempotency_key="request-1")
        repeated = self.service.create_record(1, **self.facts, idempotency_key="request-1")
        self.assertEqual(first.id, repeated.id)
        with self.assertRaises(HealthRecordConflict):
            self.service.create_record(1, **{**self.facts, "title": "另一事件"}, idempotency_key="request-1")
        self.assertEqual(self.count(), (1, 1))

    def test_simultaneous_retries_rollback_losing_record(self):
        barrier, entered = threading.Barrier(2), threading.local()
        original = self.service._replay
        def synchronized(*args):
            existing = original(*args)
            if not getattr(entered, "seen", False):
                entered.seen = True
                barrier.wait(timeout=5)
            return existing
        with patch.object(self.service, "_replay", synchronized), ThreadPoolExecutor(max_workers=2) as pool:
            jobs = [pool.submit(self.service.create_record, 1, **self.facts, idempotency_key="concurrent") for _ in range(2)]
            ids = [job.result(timeout=10).id for job in jobs]
        self.assertEqual(ids[0], ids[1])
        self.assertEqual(self.count(), (1, 1))
        with self.db.get_session() as session:
            self.assertEqual(session.query(HealthRecordVersion).count(), 1)
            self.assertEqual(session.query(HealthRecordRevision).count(), 1)

    def test_same_key_different_users_are_independent(self):
        one = self.service.create_record(1, **self.facts, idempotency_key="same")
        two = self.service.create_record(2, **self.facts, idempotency_key="same")
        self.assertNotEqual(one.id, two.id)
        self.assertIsNone(self.service.get_record(2, one.id))
        self.assertIsNone(self.service.update_record(2, one.id, summary="错误用户"))
        self.assertFalse(self.service.delete_record(2, one.id))

    def test_deleted_record_cannot_be_resurrected_by_retry(self):
        record = self.service.create_record(1, **self.facts, idempotency_key="delete-test")
        self.assertTrue(self.service.delete_record(1, record.id))
        with self.assertRaises(HealthRecordConflict):
            self.service.create_record(1, **self.facts, idempotency_key="delete-test")
        self.assertEqual(self.service.list_records(1), [])
        self.assertEqual(self.count(), (1, 1))

    def test_unknown_time_retry_keeps_original_reference_time(self):
        first = self.service.create_record(1, **{**self.facts, "time_precision": "unknown"}, idempotency_key="unknown")
        second = self.service.create_record(1, **{**self.facts, "time_precision": "unknown", "observed_at": datetime(2026, 1, 2)}, idempotency_key="unknown")
        self.assertEqual(first.id, second.id)
        self.assertEqual(second.observed_at, first.observed_at)

    def test_end_date_includes_last_microsecond(self):
        record = self.service.create_record(1, **{**self.facts, "observed_at": datetime(2026, 1, 1, 23, 59, 59, 999999)})
        self.assertEqual([r.id for r in self.service.list_records(1, date(2026, 1, 1), date(2026, 1, 1))], [record.id])

    def test_updates_cannot_change_owner_or_internal_fields(self):
        record = self.service.create_record(1, **self.facts)
        for changes in ({"user_id": 2}, {"id": 8}, {"status": "deleted"}, {"source": "manual"}, {"title": " "}, {"details": []}):
            with self.subTest(changes=changes), self.assertRaises((ValueError, TypeError)):
                self.service.update_record(1, record.id, **changes)
        updated = self.service.update_record(1, record.id, observed_at=datetime(2026, 1, 1, 18, tzinfo=timezone.utc), time_precision="minute")
        self.assertEqual(updated.observed_at, datetime(2026, 1, 2, 2))
        self.assertEqual(updated.details, self.facts["details"])

    def test_database_failure_is_not_an_empty_list(self):
        with patch.object(self.db, "get_session", side_effect=RuntimeError("synthetic offline")):
            with self.assertRaises(RuntimeError):
                self.service.list_records(1)

    def test_revision_history_and_stale_updates(self):
        record = self.service.create_record(1, **self.facts)
        updated = self.service.update_record(1, record.id, expected_revision=1,
            actor_message_id="message-2", summary="用户补充合成情况")
        self.assertEqual(updated.to_dict()["revision"], 2)
        with self.assertRaisesRegex(HealthRecordConflict, "revision_conflict"):
            self.service.update_record(1, record.id, expected_revision=1, summary="过期更新")
        history = self.service.get_history(1, record.id)
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["before"]["summary"], "合成测试")
        self.assertEqual(history[0]["after"]["summary"], "用户补充合成情况")
        self.assertEqual(history[0]["actor_message_id"], "message-2")
        self.assertIsNone(self.service.get_history(2, record.id))

    def test_history_failure_rolls_back_record_and_revision(self):
        record = self.service.create_record(1, **self.facts)
        with patch.object(self.service, "_history", side_effect=RuntimeError("injected history failure")):
            with self.assertRaises(RuntimeError):
                self.service.update_record(1, record.id, summary="不能部分保存")
        current = self.service.get_record(1, record.id)
        self.assertEqual(current.summary, "合成测试")
        self.assertEqual(current.to_dict()["revision"], 1)
        self.assertEqual(len(self.service.get_history(1, record.id)), 1)

    def test_noop_correction_does_not_increment_revision(self):
        record = self.service.create_record(1, **self.facts)
        result = self.service.update_record(1, record.id, summary="合成测试")
        self.assertEqual(result.to_dict()["revision"], 1)
        self.assertEqual(len(self.service.get_history(1, record.id)), 1)

    def test_public_detail_edit_keeps_time_provenance_and_time_correction_confirms_it(self):
        record = self.service.create_record(1, **{**self.facts, "time_precision": "unknown", "confidence": "inferred_time",
            "details": {"body_site": "头部", "_time": {"expression": "昨天"}}})
        edited = self.service.update_record(1, record.id, details={"body_site": "太阳穴"})
        self.assertEqual(edited.time_precision, "unknown")
        self.assertEqual(edited.details["_time"]["expression"], "昨天")
        corrected = self.service.update_record(1, record.id, observed_at=datetime(2026, 1, 1, 18), time_precision="minute")
        self.assertEqual(corrected.confidence, "user_confirmed")

    def test_concurrent_corrections_do_not_silently_overwrite(self):
        record = self.service.create_record(1, **self.facts)
        barrier = threading.Barrier(2)
        original = self.service._advance_revision
        def synchronized(*args):
            barrier.wait(timeout=5)
            return original(*args)
        with patch.object(self.service, "_advance_revision", synchronized), ThreadPoolExecutor(max_workers=2) as pool:
            jobs = [pool.submit(self.service.update_record, 1, record.id, expected_revision=1, summary=value)
                    for value in ("更正A", "更正B")]
            outcomes = []
            for job in jobs:
                try:
                    outcomes.append(job.result(timeout=10))
                except HealthRecordConflict:
                    outcomes.append(None)
        self.assertEqual(sum(value is not None for value in outcomes), 1)
        self.assertEqual(self.service.get_record(1, record.id).to_dict()["revision"], 2)
        self.assertEqual(len(self.service.get_history(1, record.id)), 2)

    def test_additive_schema_keeps_existing_records_and_is_repeatable(self):
        from service.services.health_record_admin import prepare
        record = self.service.create_record(1, **self.facts)
        with self.db.engine.begin() as connection:
            HealthRecordReceipt.__table__.drop(connection)
        migrated = prepare(self.db, Path(self.directory.name) / "backups")
        self.assertEqual(migrated["status"], "prepared")
        self.assertTrue(Path(migrated["backup"]).is_file())
        self.assertEqual(prepare(self.db, Path(self.directory.name) / "backups")["status"], "already_prepared")
        self.assertEqual(self.service.get_record(1, record.id).summary, "合成测试")
        self.assertEqual(self.count(), (1, 0))

    def test_mcp_ambiguity_and_partial_correction(self):
        path = Path(__file__).resolve().parents[1] / "mcp-serve" / "health_tools.py"
        spec = importlib.util.spec_from_file_location("synthetic_health_tools", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        class Registry:
            def __init__(self): self.functions = {}
            def tool(self, fn):
                self.functions[fn.__name__] = fn
                return fn
        registry = Registry()
        with patch.object(module, "DatabaseClient", return_value=self.db):
            module.register_health_tools(registry)
        unclear = json.loads(registry.functions["create_record"](1, "medication", "用药事实", date_text="20号"))
        self.assertEqual(unclear["error"], "needs_clarification")
        self.assertEqual(self.count(), (0, 0))
        record = self.service.create_record(1, **self.facts)
        result = json.loads(registry.functions["update_record"](1, record.id, date_text="2026年1月2日晚上8点"))
        self.assertTrue(result["success"])
        self.assertEqual(result["record"]["observed_at"], "2026-01-02T20:00:00")
        self.assertEqual(result["record"]["summary"], "合成测试")
        self.assertEqual(result["record"]["details"]["body_site"], "头部")


if __name__ == "__main__":
    unittest.main()
