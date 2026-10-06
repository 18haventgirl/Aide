"""API and agent share this parsing service; confirmation is an atomic transaction."""

import hashlib
import json
import threading
from datetime import date, datetime, time
from uuid import uuid4

from sqlalchemy import update
from starlette.concurrency import run_in_threadpool

from medical_parser.documents import extract_file, extract_text
from medical_parser.extractor import extract_record
from medical_parser.schema import FIELD_LABELS, ParserError
from service.models.health_record import HealthRecord
from service.models.medical_document import MedicalDocument


class MedicalDocumentService:
    def __init__(self, db_client):
        self.db_client = db_client
        # The API and agent session adapters may run on different event loops.
        self._slots = threading.BoundedSemaphore(2)

    async def parse(self, user_id: int, name: str, *, data: bytes | None = None, text: str | None = None) -> dict:
        if not self._slots.acquire(blocking=False):
            raise ParserError("当前解析任务较多，请稍后重试。", 429)
        try:
            lines = await run_in_threadpool(extract_file, name, data) if data is not None else extract_text(text or "")
            result = await extract_record(lines)
            digest = hashlib.sha256(data if data is not None else (text or "").encode("utf-8")).hexdigest()
            return await run_in_threadpool(self._create, user_id, name, digest, result)
        finally:
            self._slots.release()

    def _create(self, user_id: int, name: str, digest: str, result: dict) -> dict:
        with self.db_client.get_session() as session:
            draft = MedicalDocument(public_id=str(uuid4()), user_id=user_id, filename=name,
                                    source_sha256=digest, result_json=json.dumps(result, ensure_ascii=False))
            session.add(draft)
            session.commit()
            session.refresh(draft)
            return self._serialize(draft)

    @staticmethod
    def _serialize(draft, full: bool = True) -> dict:
        result = json.loads(draft.result_json)
        data = {"id": draft.public_id, "filename": draft.filename, "status": draft.status,
                "document_type": result["document_type"], "health_record_id": draft.health_record_id,
                "created_at": draft.created_at.isoformat() if draft.created_at else None}
        if full:
            data.update(result=result, reviewed=json.loads(draft.reviewed_json) if draft.reviewed_json else None)
        return data

    def list(self, user_id: int) -> list[dict]:
        with self.db_client.get_session() as session:
            rows = session.query(MedicalDocument).filter_by(user_id=user_id).order_by(MedicalDocument.id.desc()).limit(50).all()
            return [self._serialize(row, False) for row in rows]

    def get(self, user_id: int, public_id: str) -> dict:
        with self.db_client.get_session() as session:
            row = session.query(MedicalDocument).filter_by(user_id=user_id, public_id=public_id).first()
            if row is None:
                raise ParserError("病历解析记录不存在。", 404)
            return self._serialize(row)

    def delete(self, user_id: int, public_id: str) -> None:
        with self.db_client.get_session() as session:
            row = session.query(MedicalDocument).filter_by(user_id=user_id, public_id=public_id).first()
            if row is None:
                raise ParserError("病历解析记录不存在。", 404)
            session.delete(row)
            session.commit()

    def confirm(self, user_id: int, public_id: str, fields: dict[str, str], observed_date: date) -> dict:
        if set(fields) != set(FIELD_LABELS) or any(len(value) > 4000 for value in fields.values()):
            raise ParserError("病历字段不完整或过长，请刷新后重试。")
        if not any(fields[k].strip() for k in ("chief_complaint", "diagnosis", "present_history", "treatment", "discharge_advice")):
            raise ParserError("请至少保留一项病历内容后再保存。")
        with self.db_client.get_session() as session:
            row = session.query(MedicalDocument).filter_by(user_id=user_id, public_id=public_id).first()
            if row is None:
                raise ParserError("病历解析记录不存在。", 404)
            if row.status == "confirmed":
                return self._serialize(row)
            # Conditional UPDATE also serializes competing confirmations on SQLite.
            claim = session.execute(update(MedicalDocument).where(
                MedicalDocument.id == row.id, MedicalDocument.status == "review",
            ).values(status="confirming").execution_options(synchronize_session=False))
            if claim.rowcount != 1:
                session.rollback()
                session.expire_all()
                row = session.query(MedicalDocument).filter_by(user_id=user_id, public_id=public_id).first()
                if row and row.status == "confirmed":
                    return self._serialize(row)
                raise ParserError("记录正在保存，请稍后重新打开。", 409)
            result = json.loads(row.result_json)
            label = "出院小结" if result["document_type"] == "discharge" else "门诊病历" if result["document_type"] == "outpatient" else "病历记录"
            summary = "\n".join(f"{FIELD_LABELS[k]}：{fields[k]}" for k in ("chief_complaint", "diagnosis", "treatment", "discharge_advice") if fields[k])
            details = {FIELD_LABELS[k]: value for k, value in fields.items() if value}
            details["病历解析编号"] = public_id
            details["文件名"] = row.filename
            details["人工修改字段"] = [FIELD_LABELS[k] for k in fields if fields[k] != result["fields"][k]["value"]]
            record = HealthRecord(user_id=user_id, observed_at=datetime.combine(observed_date, time.min),
                                  time_precision="day", record_type="visit", title=f"{label} · {fields['hospital'] or row.filename}"[:200],
                                  summary=summary, details_json=json.dumps(details, ensure_ascii=False),
                                  source="document", confidence="user_confirmed", status="active")
            session.add(record)
            session.flush()
            row.health_record_id = record.id
            row.reviewed_json = json.dumps({"fields": fields, "observed_date": observed_date.isoformat()}, ensure_ascii=False)
            row.status = "confirmed"
            session.commit()
            session.refresh(row)
            return self._serialize(row)
