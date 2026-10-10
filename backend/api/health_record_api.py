"""身体状况记录 API。"""

import logging
from calendar import monthrange
from datetime import date, datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, HTTPException, Path, Query
from pydantic import BaseModel, Field

from core.auth_core import CurrentUser, success_response, not_found_response
from service.service_manager import service_manager
from service.services.health_record_service import HealthRecordService, HealthRecordConflict
from service.services.health_time import china_local_datetime

logger = logging.getLogger(__name__)
health_record_router = APIRouter(prefix="/health-records", tags=["身体状况"])


class HealthRecordCreateRequest(BaseModel):
    observed_at: Optional[datetime] = None
    time_precision: str = Field(default="minute", pattern="^(minute|day|unknown)$")
    record_type: str = Field(default="symptom", pattern="^(symptom|vital|medication|visit)$")
    title: str = Field(..., min_length=1, max_length=200)
    summary: str = Field(default="", max_length=2000)
    details: Dict[str, Any] = Field(default_factory=dict)
    source: str = Field(default="manual", pattern="^manual$")
    source_conversation_id: Optional[str] = Field(default=None, max_length=64)
    source_message_id: Optional[str] = Field(default=None, max_length=64)
    confidence: str = Field(default="user_confirmed", pattern="^(explicit|user_confirmed|inferred_time)$")
    idempotency_key: Optional[str] = Field(default=None, min_length=1, max_length=128)


class HealthRecordUpdateRequest(BaseModel):
    expected_revision: Optional[int] = Field(default=None, ge=1)
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
    return china_local_datetime(value)


def _serialize(record) -> Dict[str, Any]:
    return record.to_dict()


@health_record_router.get("/{user_id}")
async def list_health_records(
    user_id: int = Path(...),
    start_date: Optional[date] = Query(default=None),
    end_date: Optional[date] = Query(default=None),
    limit: int = Query(default=500, ge=1, le=2000),
    offset: int = Query(default=0, ge=0, le=1000000),
    current_user: Dict[str, Any] = CurrentUser,
):
    _ensure_owner(user_id, current_user)
    if start_date and end_date and start_date > end_date:
        raise HTTPException(status_code=400, detail="开始日期不能晚于结束日期")
    page = _service().record_page(user_id, start_date, end_date, limit, offset)
    return success_response({
        **page, "records": [_serialize(record) for record in page["records"]],
        "returned": len(page["records"]),
        "user_id": user_id,
    }, "成功获取身体状况记录")


@health_record_router.get("/{user_id}/calendar")
async def health_calendar(user_id: int, month: str = Query(pattern=r"^\d{4}-\d{2}$"),
                          current_user: Dict[str, Any] = CurrentUser):
    _ensure_owner(user_id, current_user)
    try:
        year, number = map(int, month.split("-"))
        start, end = date(year, number, 1), date(year, number, monthrange(year, number)[1])
    except ValueError:
        raise HTTPException(status_code=422, detail="月份无效") from None
    counts = _service().daily_counts(user_id, start, end)
    return success_response({"month": month, "daily_counts": counts, "total": sum(counts.values())}, "成功获取日历统计")


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
    try:
        if request.source_conversation_id or request.source_message_id or any(key.startswith("_") for key in request.details):
            raise ValueError("manual create cannot claim conversation provenance")
        record = _service().create_record(
            user_id, observed_at=_local_datetime(request.observed_at),
            time_precision=request.time_precision, record_type=request.record_type,
            title=request.title, summary=request.summary, details=request.details,
            source=request.source, source_conversation_id=request.source_conversation_id,
            source_message_id=request.source_message_id, confidence=request.confidence,
            idempotency_key=request.idempotency_key,
        )
    except HealthRecordConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except ValueError:
        raise HTTPException(status_code=422, detail="身体状况记录字段无效") from None
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
    if any(value is None for value in changes.values()):
        raise HTTPException(status_code=422, detail="更新字段不能为null")
    if "details" in changes and any(key.startswith("_") for key in changes["details"]):
        raise HTTPException(status_code=422, detail="详情包含保留字段")
    if "observed_at" in changes:
        changes["observed_at"] = _local_datetime(changes["observed_at"])
    try:
        record = _service().update_record(user_id, record_id, **changes)
    except HealthRecordConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except ValueError:
        raise HTTPException(status_code=422, detail="身体状况记录字段无效") from None
    if not record:
        return not_found_response("身体状况记录不存在")
    return success_response(_serialize(record), "身体状况记录已更新")


@health_record_router.delete("/{user_id}/{record_id}")
async def delete_health_record(
    user_id: int = Path(...), record_id: int = Path(...),
    current_user: Dict[str, Any] = CurrentUser,
):
    _ensure_owner(user_id, current_user)
    try:
        deleted = _service().delete_record(user_id, record_id)
    except HealthRecordConflict:
        raise HTTPException(status_code=409, detail="记录已更新，请刷新后重试") from None
    if not deleted:
        return not_found_response("身体状况记录不存在")
    return success_response({"id": record_id}, "身体状况记录已删除")


@health_record_router.get("/{user_id}/{record_id}/history")
async def health_record_history(user_id: int, record_id: int,
                               limit: int = Query(default=100, ge=1, le=500),
                               current_user: Dict[str, Any] = CurrentUser):
    _ensure_owner(user_id, current_user)
    history = _service().get_history(user_id, record_id, limit)
    if history is None:
        return not_found_response("身体状况记录不存在")
    return success_response({"history": history, "record_id": record_id}, "成功获取更正历史")
