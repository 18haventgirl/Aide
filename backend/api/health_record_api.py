"""身体状况记录 API。"""

import logging
from collections import Counter
from datetime import date, datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, HTTPException, Path, Query
from pydantic import BaseModel, Field

from core.auth_core import CurrentUser, success_response, not_found_response
from service.service_manager import service_manager
from service.services.health_record_service import HealthRecordService

logger = logging.getLogger(__name__)
health_record_router = APIRouter(prefix="/health-records", tags=["身体状况"])


class HealthRecordCreateRequest(BaseModel):
    observed_at: Optional[datetime] = None
    time_precision: str = Field(default="minute", pattern="^(minute|day|unknown)$")
    record_type: str = Field(default="symptom", pattern="^(symptom|vital|medication|visit)$")
    title: str = Field(..., min_length=1, max_length=200)
    summary: str = Field(default="", max_length=2000)
    details: Dict[str, Any] = Field(default_factory=dict)
    source: str = Field(default="manual", pattern="^(conversation|manual)$")
    source_conversation_id: Optional[str] = Field(default=None, max_length=64)
    source_message_id: Optional[str] = Field(default=None, max_length=64)
    confidence: str = Field(default="user_confirmed", pattern="^(explicit|user_confirmed|inferred_time)$")


class HealthRecordUpdateRequest(BaseModel):
    observed_at: Optional[datetime] = None
    time_precision: Optional[str] = Field(default=None, pattern="^(minute|day|unknown)$")
    record_type: Optional[str] = Field(default=None, pattern="^(symptom|vital|medication|visit)$")
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    summary: Optional[str] = Field(default=None, max_length=2000)
    details: Optional[Dict[str, Any]] = None


def _service() -> HealthRecordService:
    return service_manager.get_service("health_record_service", HealthRecordService)


def _ensure_owner(user_id: int, current_user: Dict[str, Any]) -> None:
    if str(user_id) != str(current_user["user_id"]):
        raise HTTPException(status_code=403, detail="无权访问其他用户的身体状况")


def _local_datetime(value: Optional[datetime]) -> datetime:
    value = value or datetime.now()
    return value.replace(tzinfo=None) if value.tzinfo else value


def _serialize(record) -> Dict[str, Any]:
    return record.to_dict()


@health_record_router.get("/{user_id}")
async def list_health_records(
    user_id: int = Path(...),
    start_date: Optional[date] = Query(default=None),
    end_date: Optional[date] = Query(default=None),
    limit: int = Query(default=500, ge=1, le=2000),
    current_user: Dict[str, Any] = CurrentUser,
):
    _ensure_owner(user_id, current_user)
    if start_date and end_date and start_date > end_date:
        raise HTTPException(status_code=400, detail="开始日期不能晚于结束日期")
    records = _service().list_records(user_id, start_date, end_date, limit)
    counts = Counter(record.observed_at.date().isoformat() for record in records)
    return success_response({
        "records": [_serialize(record) for record in records],
        "daily_counts": dict(counts),
        "total": len(records),
        "user_id": user_id,
    }, "成功获取身体状况记录")


@health_record_router.get("/{user_id}/{record_id}")
async def get_health_record(
    user_id: int = Path(...), record_id: int = Path(...),
    current_user: Dict[str, Any] = CurrentUser,
):
    _ensure_owner(user_id, current_user)
    record = _service().get_record(user_id, record_id)
    if not record:
        return not_found_response("身体状况记录不存在")
    return success_response(_serialize(record), "成功获取身体状况详情")


@health_record_router.post("/{user_id}")
async def create_health_record(
    user_id: int = Path(...), request: HealthRecordCreateRequest = Body(...),
    current_user: Dict[str, Any] = CurrentUser,
):
    _ensure_owner(user_id, current_user)
    record = _service().create_record(
        user_id, observed_at=_local_datetime(request.observed_at),
        time_precision=request.time_precision, record_type=request.record_type,
        title=request.title, summary=request.summary, details=request.details,
        source=request.source, source_conversation_id=request.source_conversation_id,
        source_message_id=request.source_message_id, confidence=request.confidence,
    )
    if not record:
        raise HTTPException(status_code=500, detail="创建身体状况记录失败")
    return success_response(_serialize(record), "身体状况记录已保存")


@health_record_router.patch("/{user_id}/{record_id}")
async def update_health_record(
    user_id: int = Path(...), record_id: int = Path(...),
    request: HealthRecordUpdateRequest = Body(...),
    current_user: Dict[str, Any] = CurrentUser,
):
    _ensure_owner(user_id, current_user)
    changes = request.model_dump(exclude_unset=True)
    if "observed_at" in changes:
        changes["observed_at"] = _local_datetime(changes["observed_at"])
    record = _service().update_record(user_id, record_id, **changes)
    if not record:
        return not_found_response("身体状况记录不存在")
    return success_response(_serialize(record), "身体状况记录已更新")


@health_record_router.delete("/{user_id}/{record_id}")
async def delete_health_record(
    user_id: int = Path(...), record_id: int = Path(...),
    current_user: Dict[str, Any] = CurrentUser,
):
    _ensure_owner(user_id, current_user)
    if not _service().delete_record(user_id, record_id):
        return not_found_response("身体状况记录不存在")
    return success_response({"id": record_id}, "身体状况记录已删除")
