from datetime import datetime

from pydantic import BaseModel, Field, ConfigDict

from app.schemas.common import SLUG_PATTERN, ServiceHealth


class ServiceAuthIn(BaseModel):
    bearer_token: str | None = Field(default=None, min_length=1)
    headers: dict[str, str] = Field(default_factory=dict)

class ServiceCreate(BaseModel):
    slug: str = Field(pattern=SLUG_PATTERN)
    name: str = Field(min_length=1, max_length=128)
    url: str = Field(min_length=8, max_length=512, pattern=r"^https?://")
    auth: ServiceAuthIn | None = None
    enabled: bool = False

class ServiceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    url: str | None = Field(default=None, min_length=8, max_length=512, pattern=r"^https?://")
    auth: ServiceAuthIn | None = None
    enabled: bool | None = None

class ServiceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    name: str
    url: str
    enabled: bool
    health: ServiceHealth
    consecutive_failures: int
    last_error: str | None
    last_checked_at: datetime | None
    last_refreshed_at: datetime | None
    created_at: datetime
    updated_at: datetime

class ServiceRefreshResult(BaseModel):
    service_id: int
    discovered: int
    created: int
    updated: int
    removed: int