"""身体状况记录的本地 CRUD 服务。"""

import json
from datetime import date, datetime, time
from typing import Any, Dict, List, Optional

from core.database_core import DatabaseClient
from ..models.health_record import HealthRecord


class HealthRecordService:
    def __init__(self, db_client: Optional[DatabaseClient] = None):
        self.db_client = db_client or DatabaseClient()
        if not self.db_client._initialized:
            self.db_client.initialize()

    def create_record(self, user_id: int, *, observed_at: datetime, time_precision: str,
                      record_type: str, title: str, summary: str = "",
                      details: Optional[Dict[str, Any]] = None, source: str = "conversation",
                      source_conversation_id: Optional[str] = None,
                      source_message_id: Optional[str] = None,
                      confidence: str = "explicit") -> Optional[HealthRecord]:
        try:
            with self.db_client.get_session() as session:
                record = HealthRecord(
                    user_id=user_id, observed_at=observed_at, time_precision=time_precision,
                    record_type=record_type, title=title, summary=summary or "",
                    details_json=json.dumps(details or {}, ensure_ascii=False),
                    source=source, source_conversation_id=source_conversation_id,
                    source_message_id=source_message_id, confidence=confidence, status="active",
                )
                session.add(record)
                session.commit()
                session.refresh(record)
                return record
        except Exception as exc:
            print(f"创建身体状况记录失败: {exc}")
            return None

    def get_record(self, user_id: int, record_id: int) -> Optional[HealthRecord]:
        try:
            with self.db_client.get_session() as session:
                return session.query(HealthRecord).filter(
                    HealthRecord.id == record_id,
                    HealthRecord.user_id == user_id,
                    HealthRecord.status != "deleted",
                ).first()
        except Exception as exc:
            print(f"获取身体状况记录失败: {exc}")
            return None

    def list_records(self, user_id: int, start_date: Optional[date] = None,
                     end_date: Optional[date] = None, limit: int = 500) -> List[HealthRecord]:
        try:
            with self.db_client.get_session() as session:
                query = session.query(HealthRecord).filter(
                    HealthRecord.user_id == user_id,
                    HealthRecord.status != "deleted",
                )
                if start_date:
                    query = query.filter(HealthRecord.observed_at >= datetime.combine(start_date, time.min))
                if end_date:
                    query = query.filter(HealthRecord.observed_at < datetime.combine(end_date, time.max))
                return query.order_by(HealthRecord.observed_at.desc()).limit(limit).all()
        except Exception as exc:
            print(f"查询身体状况记录失败: {exc}")
            return []

    def update_record(self, user_id: int, record_id: int, **changes: Any) -> Optional[HealthRecord]:
        try:
            with self.db_client.get_session() as session:
                record = session.query(HealthRecord).filter(
                    HealthRecord.id == record_id, HealthRecord.user_id == user_id,
                    HealthRecord.status != "deleted",
                ).first()
                if not record:
                    return None
                if "details" in changes:
                    changes["details_json"] = json.dumps(changes.pop("details") or {}, ensure_ascii=False)
                for key, value in changes.items():
                    if hasattr(record, key) and value is not None:
                        setattr(record, key, value)
                session.commit()
                session.refresh(record)
                return record
        except Exception as exc:
            print(f"更新身体状况记录失败: {exc}")
            return None

    def delete_record(self, user_id: int, record_id: int) -> bool:
        try:
            with self.db_client.get_session() as session:
                record = session.query(HealthRecord).filter(
                    HealthRecord.id == record_id, HealthRecord.user_id == user_id,
                    HealthRecord.status != "deleted",
                ).first()
                if not record:
                    return False
                record.status = "deleted"
                session.commit()
                return True
        except Exception as exc:
            print(f"删除身体状况记录失败: {exc}")
            return False
