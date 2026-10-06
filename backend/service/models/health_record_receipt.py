"""Transactional receipts prevent duplicate creates across retries/processes."""
from sqlalchemy import Column, ForeignKey, Integer, String, UniqueConstraint
from core.database_core import BaseModel


class HealthRecordReceipt(BaseModel):
    __tablename__ = "health_record_receipts"
    user_id = Column(Integer, nullable=False)
    key_sha256 = Column(String(64), nullable=False)
    payload_sha256 = Column(String(64), nullable=False)
    record_id = Column(Integer, ForeignKey("health_records.id"), nullable=False)
    __table_args__ = (UniqueConstraint("user_id", "key_sha256", name="uq_health_receipt_owner_key"),)
