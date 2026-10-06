"""Authenticated parsing and explicit confirmation; no client-supplied owner ID."""

from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from core.auth_core import CurrentUser, success_response
from medical_parser.schema import MAX_BYTES, ParserError, TextParseRequest
from service.service_manager import service_manager
from service.services.medical_document_service import MedicalDocumentService

class MedicalDocumentRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def sanitized_handler(request: Request):
            try:
                return await handler(request)
            except RequestValidationError as exc:
                # Default validation errors include the submitted clinical text.
                raise HTTPException(422, detail="请求字段不符合要求，请检查文字长度、日期及字段内容。") from exc
        return sanitized_handler


medical_document_router = APIRouter(prefix="/medical-documents", tags=["病历解析"], route_class=MedicalDocumentRoute)


def _service() -> MedicalDocumentService:
    return service_manager.get_service("medical_document_service", MedicalDocumentService)


class ConfirmRequest(BaseModel):
    fields: dict[str, str] = Field(max_length=20)
    observed_date: date


async def _call(fn, *args):
    try:
        return success_response(await run_in_threadpool(fn, *args))
    except ParserError as exc:
        raise HTTPException(exc.status_code, detail=str(exc)) from exc


@medical_document_router.post("/parse-text")
async def parse_text(request: TextParseRequest, current_user: dict[str, Any] = CurrentUser):
    try:
        return success_response(await _service().parse(int(current_user["user_id"]), request.name, text=request.text))
    except ParserError as exc:
        raise HTTPException(exc.status_code, detail=str(exc)) from exc


@medical_document_router.post("/parse-file")
async def parse_file(request: Request, filename: str = Query(min_length=1, max_length=200),
                     current_user: dict[str, Any] = CurrentUser):
    # Raw request body avoids unbounded multipart spooling before the size check.
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_BYTES:
            raise HTTPException(413, detail="文件不能超过 10 MB。")
        body.extend(chunk)
    filename = filename.replace("\\", "/").split("/")[-1]
    try:
        return success_response(await _service().parse(int(current_user["user_id"]), filename, data=bytes(body)))
    except ParserError as exc:
        raise HTTPException(exc.status_code, detail=str(exc)) from exc


@medical_document_router.get("")
async def list_documents(current_user: dict[str, Any] = CurrentUser):
    return await _call(_service().list, int(current_user["user_id"]))


@medical_document_router.get("/{document_id}")
async def get_document(document_id: str, current_user: dict[str, Any] = CurrentUser):
    return await _call(_service().get, int(current_user["user_id"]), document_id)


@medical_document_router.post("/{document_id}/confirm")
async def confirm_document(document_id: str, request: ConfirmRequest, current_user: dict[str, Any] = CurrentUser):
    return await _call(_service().confirm, int(current_user["user_id"]), document_id, request.fields, request.observed_date)


@medical_document_router.delete("/{document_id}")
async def delete_document(document_id: str, current_user: dict[str, Any] = CurrentUser):
    return await _call(_service().delete, int(current_user["user_id"]), document_id)
