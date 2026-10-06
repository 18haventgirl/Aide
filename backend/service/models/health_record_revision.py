"""Additive revision state and transactional correction history for health facts."""
from sqlalchemy import Column, ForeignKey, Integer, String, Text, UniqueConstraint
from core.database_core import BaseModel


class HealthRecordVersion(BaseModel):
    __tablename__ = "health_record_versions"
    record_id = Column(Integer, ForeignKey("health_records.id"), nullable=False, unique=True)
    user_id = Column(Integer, nullable=False)
    revision = Column(Integer, nullable=False, default=1)


class HealthRecordRevision(BaseModel):
    __tablename__ = "health_record_revisions"
    record_id = Column(Integer, ForeignKey("health_records.id"), nullable=False)
    user_id = Column(Integer, nullable=False)
    revision = Column(Integer, nullable=False)
    operation = Column(String(16), nullable=False)
    before_json = Column(Text, nullable=True)
    after_json = Column(Text, nullable=False)
    actor_message_id = Column(String(64), nullable=True)
    __table_args__ = (UniqueConstraint("record_id", "revision", name="uq_health_revision"),)
