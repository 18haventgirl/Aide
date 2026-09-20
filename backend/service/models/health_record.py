"""用户身体状况记录模型。"""

import json
from typing import Any, Dict

from sqlalchemy import Column, DateTime, Index, Integer, String, Text

from core.database_core import BaseModel


class HealthRecord(BaseModel):
    """只保存用户明确表达或手动填写的健康事实。"""

    __tablename__ = "health_records"

    user_id = Column(Integer, nullable=False, comment="所属用户")
    observed_at = Column(DateTime, nullable=False, comment="事实发生时间（本地时间）")
    time_precision = Column(String(16), nullable=False, default="unknown", comment="minute/day/unknown")
    record_type = Column(String(24), nullable=False, comment="symptom/vital/medication/visit")
    title = Column(String(200), nullable=False, comment="记录标题")
    summary = Column(Text, nullable=False, default="", comment="用户可读摘要")
    details_json = Column(Text, nullable=False, default="{}", comment="结构化详情 JSON")
    source = Column(String(24), nullable=False, default="conversation", comment="conversation/manual")
    source_conversation_id = Column(String(64), nullable=True, comment="来源会话")
    source_message_id = Column(String(64), nullable=True, comment="来源消息")
    confidence = Column(String(24), nullable=False, default="explicit", comment="explicit/user_confirmed/inferred_time")
    status = Column(String(16), nullable=False, default="active", comment="active/corrected/deleted")

    __table_args__ = (
        Index("idx_health_records_user_observed", "user_id", "observed_at"),
        Index("idx_health_records_user_status", "user_id", "status"),
        Index("idx_health_records_user_type", "user_id", "record_type"),
    )

    @property
    def details(self) -> Dict[str, Any]:
        try:
            value = json.loads(self.details_json or "{}")
            return value if isinstance(value, dict) else {}
        except (TypeError, ValueError):
            return {}

    @details.setter
    def details(self, value: Dict[str, Any]) -> None:
        self.details_json = json.dumps(value or {}, ensure_ascii=False)

    def to_dict(self) -> Dict[str, Any]:
        data = super().to_dict()
        data["details"] = self.details
        data.pop("details_json", None)
        return data
