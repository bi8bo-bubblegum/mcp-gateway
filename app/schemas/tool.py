from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.schemas.common import RiskLevel, UTCTimestampModel


class ToolRead(UTCTimestampModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    service_id: int
    service_slug: str
    upstream_name: str
    effective_name: str
    description: str | None
    input_schema: dict[str, Any]
    schema_hash: str
    risk: RiskLevel
    enabled: bool
    discovered_at: datetime
    updated_at: datetime

class ToolUpdate(BaseModel):
    risk: RiskLevel | None = None
    enabled: bool | None = None