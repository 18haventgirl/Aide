"""Versioned contract for outpatient records and discharge summaries."""

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "medical-record.v1"
MAX_BYTES = 10 * 1024 * 1024
MAX_TEXT = 40000
MAX_PAGES = 12
FIELD_LABELS = {
    "patient_name": "姓名", "sex": "性别", "age": "年龄",
    "hospital": "医疗机构", "department": "科室", "visit_date": "就诊日期",
    "admission_date": "入院日期", "discharge_date": "出院日期",
    "chief_complaint": "主诉", "present_history": "现病史",
    "past_history": "既往史", "allergies": "过敏史",
    "examination": "查体与检查", "diagnosis": "原文诊断",
    "treatment": "诊疗经过 / 用药", "discharge_advice": "医嘱 / 随访",
}


class ParserError(Exception):
    def __init__(self, message: str, status_code: int = 422):
        super().__init__(message)
        self.status_code = status_code


class SourceLine(BaseModel):
    id: str
    page: int
    text: str
    method: Literal["text", "pdf", "docx", "ocr"]
    confidence: float | None = None


class ExtractedField(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: str = Field(default="", max_length=4000)
    line_ids: list[str] = Field(default_factory=list, max_length=100)


class ModelExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_type: Literal["outpatient", "discharge", "unknown"]
    fields: dict[str, ExtractedField]


class TextParseRequest(BaseModel):
    text: str = Field(min_length=10, max_length=MAX_TEXT)
    name: str = Field(default="粘贴的病历", min_length=1, max_length=200)
