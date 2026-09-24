from datetime import datetime
from pydantic import BaseModel, ConfigDict

from app.schemas.common import AuditStatus

class AuditEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    request_id: str
    token_id: int | None
    token_name: str | None
    service_slug: str | None
    tool_name: str
    status: AuditStatus
    denial_reason: str | None
    error_type: str | None
    argument_keys: list[str]
    requested_argument_hashes: dict[str, str]
    effective_argument_hashes: dict[str, str] | None
    started_at: datetime
    finished_at: datetime | None
    duration_ms: int | None

class AuditEventPage(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[AuditEventRead]