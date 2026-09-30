"""AI 网关请求/响应模型。

字段严格对齐设计文档 §3：枚举类字段用 Literal 约束取值，slug 复用 SLUG_PATTERN，
时间字段继承 UTCTimestampModel（给库里的 naive UTC 补时区标记再输出，避免前端
按本地时间误读）。
"""
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import (
    AI_KEY_PERIOD_DAY,
    AI_KEY_PERIOD_MONTH,
    AI_KEY_PERIOD_NONE,
    AI_MODEL_KIND_CHAT,
    AI_MODEL_KIND_EMBEDDING,
    GUARDRAIL_ACTION_BLOCK,
    GUARDRAIL_SCOPE_BOTH,
    GUARDRAIL_SCOPE_REQUEST,
    GUARDRAIL_SCOPE_RESPONSE,
)
from app.schemas.common import SLUG_PATTERN, UTCTimestampModel

AiModelKind = Literal[AI_MODEL_KIND_CHAT, AI_MODEL_KIND_EMBEDDING]
AiKeyPeriod = Literal[AI_KEY_PERIOD_DAY, AI_KEY_PERIOD_MONTH, AI_KEY_PERIOD_NONE]
GuardrailScope = Literal[
    GUARDRAIL_SCOPE_REQUEST, GUARDRAIL_SCOPE_RESPONSE, GUARDRAIL_SCOPE_BOTH
]
GuardrailAction = Literal[GUARDRAIL_ACTION_BLOCK]


# ── 厂商 ──────────────────────────────────────────────────────────
class AiProviderCreate(BaseModel):
    slug: str = Field(pattern=SLUG_PATTERN)
    name: str = Field(min_length=1, max_length=128)
    base_url: str = Field(min_length=8, max_length=512, pattern=r"^https?://")
    # 上游密钥明文：落库前由服务用 SecretBox 加密，Read 绝不含此字段
    api_key: str | None = Field(default=None, min_length=1)
    enabled: bool = False


class AiProviderUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    base_url: str | None = Field(default=None, min_length=8, max_length=512, pattern=r"^https?://")
    api_key: str | None = Field(default=None, min_length=1)
    enabled: bool | None = None


class AiProviderRead(UTCTimestampModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    name: str
    base_url: str
    enabled: bool
    health: str
    consecutive_failures: int
    last_error: str | None
    last_checked_at: datetime | None
    created_at: datetime
    updated_at: datetime


# ── 模型 ──────────────────────────────────────────────────────────
class AiModelCreate(BaseModel):
    provider_id: int
    provider_model_name: str = Field(min_length=1, max_length=128)
    alias: str = Field(min_length=1, max_length=128)
    kind: AiModelKind = AI_MODEL_KIND_CHAT
    enabled: bool = True
    input_price: float | None = None
    output_price: float | None = None


class AiModelUpdate(BaseModel):
    provider_model_name: str | None = Field(default=None, min_length=1, max_length=128)
    alias: str | None = Field(default=None, min_length=1, max_length=128)
    kind: AiModelKind | None = None
    enabled: bool | None = None
    input_price: float | None = None
    output_price: float | None = None


class AiModelRead(UTCTimestampModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    provider_id: int
    provider_model_name: str
    alias: str
    kind: AiModelKind
    enabled: bool
    input_price: float | None
    output_price: float | None
    created_at: datetime
    updated_at: datetime


class AiPullModelRead(BaseModel):
    """上游 /v1/models 返回的候选模型（仅透出挑选所需的最小字段）。"""

    id: str
    owned_by: str | None = None


class AiModelImportItem(BaseModel):
    """批量导入的一条候选：上游名必填，alias 缺省则与上游名一致。"""

    provider_model_name: str = Field(min_length=1, max_length=128)
    alias: str | None = Field(default=None, min_length=1, max_length=128)
    kind: AiModelKind = AI_MODEL_KIND_CHAT


class AiModelImportRequest(BaseModel):
    provider_id: int
    items: list[AiModelImportItem] = Field(default_factory=list)


# ── AI Key ───────────────────────────────────────────────────────
class AiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    owner: str | None = Field(default=None, max_length=128)
    period_token_limit: int | None = Field(default=None, ge=0)
    period: AiKeyPeriod = AI_KEY_PERIOD_NONE
    rate_limit_rpm: int | None = Field(default=None, ge=1)
    model_ids: list[int] = Field(default_factory=list)


class AiKeyRead(UTCTimestampModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    key_prefix: str
    owner: str | None
    enabled: bool
    revoked_at: datetime | None
    period_token_limit: int | None
    period: AiKeyPeriod
    rate_limit_rpm: int | None
    created_at: datetime
    last_used_at: datetime | None


class AiKeyCreated(AiKeyRead):
    # 明文只在创建响应出现一次，库里只存哈希
    key: str


class AiKeyDetail(AiKeyRead):
    # 详情接口额外带授权模型 id，供编辑抽屉回填多选
    model_ids: list[int] = Field(default_factory=list)


class AiKeyPolicyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    enabled: bool | None = None
    period_token_limit: int | None = Field(default=None, ge=0)
    period: AiKeyPeriod | None = None
    rate_limit_rpm: int | None = Field(default=None, ge=1)
    # 提供即整体替换授权模型；None 表示本字段不参与本次更新
    model_ids: list[int] | None = None


# ── 用量审计 ──────────────────────────────────────────────────────
class AiUsageEventRead(UTCTimestampModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    request_id: str
    key_id: int | None
    key_name: str | None
    model_id: int | None
    model_alias: str | None
    provider_slug: str | None
    endpoint: str
    stream: bool
    status: str
    denial_reason: str | None
    error_type: str | None
    upstream_status_code: int | None
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    usage_estimated: bool
    guardrail_hits: list | None
    latency_ms: int | None
    first_token_ms: int | None
    started_at: datetime
    finished_at: datetime | None


class AiUsageEventPage(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[AiUsageEventRead] = Field(default_factory=list)


class AiUsageDailyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key_id: int
    # day 是纯日期（无时区），不继承 UTCTimestampModel
    day: date
    requests: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


# ── 护栏规则 ──────────────────────────────────────────────────────
class GuardrailRuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    pattern: str = Field(min_length=1, max_length=512)
    scope: GuardrailScope = GUARDRAIL_SCOPE_REQUEST
    action: GuardrailAction = GUARDRAIL_ACTION_BLOCK
    enabled: bool = True


class GuardrailRuleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    pattern: str | None = Field(default=None, min_length=1, max_length=512)
    scope: GuardrailScope | None = None
    action: GuardrailAction | None = None
    enabled: bool | None = None


class GuardrailRuleRead(UTCTimestampModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    pattern: str
    scope: GuardrailScope
    action: GuardrailAction
    enabled: bool
    created_at: datetime
    updated_at: datetime


class GuardrailBulkCreate(BaseModel):
    """批量导入：text 按行拆成关键词，每行一条规则（规则名取该行文本）。"""

    name_prefix: str = Field(default="", max_length=64)
    text: str = Field(min_length=1)
    scope: GuardrailScope = GUARDRAIL_SCOPE_REQUEST
    action: GuardrailAction = GUARDRAIL_ACTION_BLOCK
    enabled: bool = True


class GuardrailBulkResult(BaseModel):
    created: int
    skipped: int
    rules: list[GuardrailRuleRead] = Field(default_factory=list)
