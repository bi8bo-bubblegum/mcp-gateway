from datetime import datetime
from typing import Any
from pydantic import BaseModel, ConfigDict, Field

class ParameterInjectionIn(BaseModel):
    tool_id: int
    argument: str = Field(min_length=1, max_length=128)
    value: Any

class ParameterInjectionRead(ParameterInjectionIn):

    model_config = ConfigDict(from_attributes=True)

    id: int

class TokenCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    allow_high_risk: bool = False
    visible_service_ids: list[int] = Field(default_factory=list)
    allowed_tool_ids: list[int] = Field(default_factory=list)
    parameter_injections: list[ParameterInjectionIn] = Field(default_factory=list)

class TokenPolicyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    enabled: bool | None = None
    allow_high_risk: bool | None = None
    visible_service_ids: list[int] | None = None
    allowed_tool_ids: list[int] | None = None
    parameter_injections: list[ParameterInjectionIn] | None = None

class TokenRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    token_prefix: str
    enabled: bool
    allow_high_risk: bool
    created_at: datetime
    revoked_at: datetime | None
    last_used_at: datetime | None
    visible_service_ids: list[int] = Field(default_factory=list)
    allowed_tool_ids: list[int] = Field(default_factory=list)
    parameter_injections: list[ParameterInjectionRead] = Field(default_factory=list)

class TokenCreated(TokenRead):
    token: str

