"""Successful parse drafts, isolated by authenticated user."""

from sqlalchemy import Column, Integer, String, Text, Index
from core.database_core import BaseModel


class MedicalDocument(BaseModel):
    __tablename__ = "medical_documents"
    public_id = Column(String(36), nullable=False, unique=True)
    user_id = Column(Integer, nullable=False)
    filename = Column(String(200), nullable=False)
    source_sha256 = Column(String(64), nullable=False)
    status = Column(String(16), nullable=False, default="review")
    result_json = Column(Text, nullable=False)
    reviewed_json = Column(Text, nullable=True)
    health_record_id = Column(Integer, nullable=True)
    __table_args__ = (Index("idx_medical_documents_user_created", "user_id", "created_at"),)
