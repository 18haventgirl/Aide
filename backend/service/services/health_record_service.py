"""Owner-scoped health records with transactionally idempotent creation."""
import hashlib
import json
from datetime import date, datetime, time
from typing import Any, Dict, List, Optional

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from core.database_core import DatabaseClient
from ..models.health_record import HealthRecord
from ..models.health_record_receipt import HealthRecordReceipt
from ..models.health_record_revision import HealthRecordVersion, HealthRecordRevision
from .health_time import china_local_datetime


class HealthRecordConflict(ValueError):
    """A create key was reused for different facts, or its record was deleted."""


def _json(value):
    if not isinstance(value, dict):
        raise ValueError("details must be a JSON object")
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def _validate(fields):
    choices = {"time_precision": {"minute", "day", "unknown"},
               "record_type": {"symptom", "vital", "medication", "visit"},
               "source": {"conversation", "manual"},
               "confidence": {"explicit", "user_confirmed", "inferred_time"}}
    for key, values in choices.items():
        if key in fields and fields[key] not in values:
            raise ValueError(f"invalid {key}")
    if "title" in fields and (not isinstance(fields["title"], str) or not fields["title"].strip() or len(fields["title"]) > 200):
        raise ValueError("invalid title")
    if "summary" in fields and (not isinstance(fields["summary"], str) or len(fields["summary"]) > 2000):
        raise ValueError("invalid summary")
    if "details" in fields:
        _json(fields["details"])


class HealthRecordService:
    def __init__(self, db_client: Optional[DatabaseClient] = None):
        self.db_client = db_client or DatabaseClient()
        if not self.db_client._initialized and not self.db_client.initialize():
            raise RuntimeError("health database initialization failed")

    @staticmethod
    def _owned(session, user_id, record_id, include_deleted=False):
        query = session.query(HealthRecord).filter(HealthRecord.id == record_id, HealthRecord.user_id == user_id)
        return (query if include_deleted else query.filter(HealthRecord.status != "deleted")).first()

    @staticmethod
    def _attach_revision(session, record):
        if record is not None:
            version = session.query(HealthRecordVersion.revision).filter_by(record_id=record.id, user_id=record.user_id).scalar()
            record._record_revision = version or 1
        return record

    @staticmethod
    def _advance_revision(session, record, expected_revision=None):
        state = session.query(HealthRecordVersion).filter_by(record_id=record.id, user_id=record.user_id).first()
        if state is None:
            state = HealthRecordVersion(record_id=record.id, user_id=record.user_id, revision=1)
            session.add(state)
            session.flush()
        if expected_revision is not None and expected_revision != state.revision:
            raise HealthRecordConflict("revision_conflict")
        old = state.revision
        changed = session.execute(update(HealthRecordVersion).where(
            HealthRecordVersion.record_id == record.id, HealthRecordVersion.user_id == record.user_id,
            HealthRecordVersion.revision == old).values(revision=old+1), execution_options={"synchronize_session": False}).rowcount
        if changed != 1:
            raise HealthRecordConflict("revision_conflict")
        return old+1

    @staticmethod
    def _history(session, record, operation, before=None, actor_message_id=None):
        session.add(HealthRecordRevision(record_id=record.id, user_id=record.user_id,
            revision=record._record_revision, operation=operation,
            before_json=_json(before) if before is not None else None,
            after_json=_json(record.to_dict()), actor_message_id=actor_message_id))

    def _replay(self, session, user_id, key, fingerprint):
        receipt = session.query(HealthRecordReceipt).filter_by(user_id=user_id, key_sha256=key).first()
        if not receipt:
            return None
        if receipt.payload_sha256 != fingerprint:
            raise HealthRecordConflict("idempotency_payload_conflict")
        record = self._owned(session, user_id, receipt.record_id, include_deleted=True)
        if record is None or record.status == "deleted":
            raise HealthRecordConflict("idempotency_record_deleted")
        return self._attach_revision(session, record)

    def create_record(self, user_id: int, *, observed_at: datetime, time_precision: str,
                      record_type: str, title: str, summary: str = "",
                      details: Optional[Dict[str, Any]] = None, source: str = "conversation",
                      source_conversation_id: Optional[str] = None,
                      source_message_id: Optional[str] = None,
                      confidence: str = "explicit", idempotency_key: Optional[str] = None) -> HealthRecord:
        facts = {} if details is None else details
        fields = dict(time_precision=time_precision, record_type=record_type, title=title,
                      summary=summary, details=facts, source=source, confidence=confidence)
        _validate(fields)
        if idempotency_key is not None and (not isinstance(idempotency_key, str) or not idempotency_key.strip() or len(idempotency_key) > 128):
            raise ValueError("idempotency_key must contain 1-128 characters")
        observed_at = china_local_datetime(observed_at)
        if time_precision == "day":
            observed_at = observed_at.replace(hour=0, minute=0, second=0, microsecond=0)
        fields.update(observed_at=observed_at.isoformat() if time_precision != "unknown" else "inferred",
                      source_conversation_id=source_conversation_id, source_message_id=source_message_id)
        fingerprint = hashlib.sha256(_json(fields).encode()).hexdigest()
        key = hashlib.sha256(idempotency_key.encode()).hexdigest() if idempotency_key else None
        try:
            with self.db_client.get_session() as session:
                existing = self._replay(session, user_id, key, fingerprint) if key else None
                if existing:
                    return existing
                record = HealthRecord(user_id=user_id, observed_at=observed_at, time_precision=time_precision,
                    record_type=record_type, title=title, summary=summary, details_json=_json(facts),
                    source=source, source_conversation_id=source_conversation_id,
                    source_message_id=source_message_id, confidence=confidence, status="active")
                session.add(record)
                session.flush()
                record._record_revision = 1
                session.add(HealthRecordVersion(record_id=record.id, user_id=user_id, revision=1))
                self._history(session, record, "created", actor_message_id=source_message_id)
                if key:
                    session.add(HealthRecordReceipt(user_id=user_id, key_sha256=key,
                                                   payload_sha256=fingerprint, record_id=record.id))
                session.commit()
                session.refresh(record)
                return record
        except IntegrityError:
            # Unique constraints resolve concurrent creates; losing transactions
            # roll back their new record together with the duplicate receipt.
            if key:
                with self.db_client.get_session() as session:
                    existing = self._replay(session, user_id, key, fingerprint)
                    if existing:
                        return existing
            raise

    def get_record(self, user_id: int, record_id: int) -> Optional[HealthRecord]:
        with self.db_client.get_session() as session:
            return self._attach_revision(session, self._owned(session, user_id, record_id))

    def list_records(self, user_id: int, start_date: Optional[date] = None,
                     end_date: Optional[date] = None, limit: int = 500) -> List[HealthRecord]:
        if start_date and end_date and start_date > end_date:
            raise ValueError("start_date exceeds end_date")
        if not 1 <= limit <= 2000:
            raise ValueError("invalid limit")
        with self.db_client.get_session() as session:
            query = session.query(HealthRecord).filter(HealthRecord.user_id == user_id, HealthRecord.status != "deleted")
            if start_date:
                query = query.filter(HealthRecord.observed_at >= datetime.combine(start_date, time.min))
            if end_date:
                query = query.filter(HealthRecord.observed_at <= datetime.combine(end_date, time.max))
            records = query.order_by(HealthRecord.observed_at.desc(), HealthRecord.id.desc()).limit(limit).all()
            if records:
                versions = dict(session.query(HealthRecordVersion.record_id, HealthRecordVersion.revision).filter(
                    HealthRecordVersion.user_id == user_id, HealthRecordVersion.record_id.in_([r.id for r in records])).all())
                for record in records:
                    record._record_revision = versions.get(record.id, 1)
            return records

    def update_record(self, user_id: int, record_id: int, *, expected_revision: Optional[int] = None,
                      actor_message_id: Optional[str] = None, **changes: Any) -> Optional[HealthRecord]:
        if expected_revision is not None and (not isinstance(expected_revision, int) or expected_revision < 1):
            raise ValueError("invalid expected_revision")
        allowed = {"observed_at", "time_precision", "record_type", "title", "summary", "details"}
        if set(changes) - allowed or any(v is None for v in changes.values()):
            raise ValueError("invalid health record update fields")
        _validate(changes)
        with self.db_client.get_session() as session:
            record = self._attach_revision(session, self._owned(session, user_id, record_id))
            if not record:
                return None
            if not changes:
                return record
            before = record.to_dict()
            if "details" in changes:
                changes["details_json"] = _json(changes.pop("details"))
            if "observed_at" in changes:
                changes["observed_at"] = china_local_datetime(changes["observed_at"])
            if changes.get("time_precision", record.time_precision) == "day":
                changes["observed_at"] = changes.get("observed_at", record.observed_at).replace(hour=0, minute=0, second=0, microsecond=0)
            if expected_revision is not None and record._record_revision != expected_revision:
                raise HealthRecordConflict("revision_conflict")
            if all(getattr(record, key) == value for key, value in changes.items()):
                return record
            record._record_revision = self._advance_revision(session, record, record._record_revision)
            for key, value in changes.items():
                setattr(record, key, value)
            session.flush()
            self._history(session, record, "updated", before, actor_message_id)
            session.commit()
            session.refresh(record)
            return record

    def delete_record(self, user_id: int, record_id: int) -> bool:
        with self.db_client.get_session() as session:
            record = self._attach_revision(session, self._owned(session, user_id, record_id))
            if not record:
                return False
            before = record.to_dict()
            record._record_revision = self._advance_revision(session, record, record._record_revision)
            record.status = "deleted"
            session.flush()
            self._history(session, record, "deleted", before)
            session.commit()
            return True

    def get_history(self, user_id: int, record_id: int, limit=100) -> Optional[List[dict]]:
        if not 1 <= limit <= 500:
            raise ValueError("invalid history limit")
        with self.db_client.get_session() as session:
            if self._owned(session, user_id, record_id) is None:
                return None
            rows = session.query(HealthRecordRevision).filter_by(user_id=user_id, record_id=record_id).order_by(
                HealthRecordRevision.revision.desc()).limit(limit).all()
            return [{"revision": row.revision, "operation": row.operation,
                     "before": json.loads(row.before_json) if row.before_json else None,
                     "after": json.loads(row.after_json), "actor_message_id": row.actor_message_id,
                     "at": row.created_at.isoformat()} for row in rows]
