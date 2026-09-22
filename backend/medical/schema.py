"""Data contracts for the curated medical corpus."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, model_validator


class MedicalDocument(BaseModel):
    doc_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    version: int = Field(ge=1)
    title: str = Field(min_length=2)
    topic: str = Field(min_length=2)
    audience: str = Field(min_length=2)
    source_org: str = Field(min_length=2)
    source_url: HttpUrl
    source_published_at: date
    # "draft" is accepted only for the isolated legacy preview collection.
    status: Literal["draft", "collected", "source_checked", "clinician_reviewed", "retired"]
    reviewer: str | None = None
    reviewed_at: date | None = None
    next_review_at: date | None = None
    license_note: str = Field(min_length=2)
    source_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    source_locator: str | None = None
    source_collected_at: date | None = None
    source_version: str | None = None
    usage_scope: str | None = None
    withdrawn: bool = False
    body: str = Field(min_length=1)

    @model_validator(mode="after")
    def reviewed_document_needs_audit(self):
        if self.status in {"source_checked", "clinician_reviewed"}:
            if not self.reviewer or not self.reviewed_at or not self.next_review_at:
                raise ValueError("checked documents require reviewer and review dates")
            if self.next_review_at < self.reviewed_at:
                raise ValueError("next_review_at precedes reviewed_at")
            if not self.source_sha256 or not self.source_locator or not self.source_collected_at:
                raise ValueError("checked documents require source hash, locator and collection date")
        return self

    def is_searchable(self, today: date, research_mode: bool = False) -> bool:
        allowed = {"source_checked", "clinician_reviewed"} if research_mode else {"clinician_reviewed"}
        return (not self.withdrawn and self.status in allowed
                and bool(self.next_review_at and self.next_review_at >= today))


class MedicalHit(BaseModel):
    chunk_id: str
    doc_id: str
    title: str
    section_path: str
    text: str
    source_org: str
    source_url: str
    source_locator: str | None = None
    source_published_at: date | None = None
    source_version: str | None = None
    source_sha256: str | None = None
    status: str | None = None
    reviewed_at: date | None = None
    next_review_at: date | None = None
    distance: float | None = None
    dense_rank: int | None = None
    lexical_rank: int | None = None
    lexical_score: float | None = None
    fusion_score: float | None = None
    rerank_score: float | None = None
    retrieval_method: str = "dense"
