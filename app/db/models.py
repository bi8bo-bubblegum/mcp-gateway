from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TIMESTAMP, utcnow


class GatewayRevision(Base):
    """Single-row table holding the global configuration revision."""

    __tablename__ = "gateway_revision"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    revision: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class Service(Base):
    """A registered upstream MCP server reachable over Streamable HTTP."""

    __tablename__ = "services"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    url: Mapped[str] = mapped_column(String(512), nullable=False)
    auth_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    health: Mapped[str] = mapped_column(String(16), default="unknown", nullable=False)
    consecutive_failures: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(TIMESTAMP, nullable=True)
    last_refreshed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, default=utcnow, onupdate=utcnow, nullable=False
    )

    tools: Mapped[list["Tool"]] = relationship(
        back_populates="service",
        cascade="all, delete-orphan",
    )


class Tool(Base):
    """A tool discovered from an upstream server."""

    __tablename__ = "tools"
    __table_args__ = (
        UniqueConstraint("service_id", "upstream_name", name="uq_tools_service_upstream"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    service_id: Mapped[int] = mapped_column(
        ForeignKey("services.id", ondelete="CASCADE"), nullable=False
    )
    upstream_name: Mapped[str] = mapped_column(String(128), nullable=False)
    effective_name: Mapped[str] = mapped_column(
        String(256), unique=True, nullable=False
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_schema: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    schema_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # New tools default to high risk: an admin must confirm before any token may call them.
    risk: Mapped[str] = mapped_column(String(8), default="high", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    available: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    discovered_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, default=utcnow, onupdate=utcnow, nullable=False
    )

    service: Mapped[Service] = relationship(back_populates="tools")


class Token(Base):
    """An admin-created gateway credential. Only the HMAC hash is stored."""

    __tablename__ = "tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    token_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    allow_high_risk: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, default=utcnow, nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(TIMESTAMP, nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(TIMESTAMP, nullable=True)


class TokenService(Base):
    """Level 1: which upstream servers a token may see."""

    __tablename__ = "token_services"

    token_id: Mapped[int] = mapped_column(
        ForeignKey("tokens.id", ondelete="CASCADE"), primary_key=True
    )
    service_id: Mapped[int] = mapped_column(
        ForeignKey("services.id", ondelete="CASCADE"), primary_key=True
    )


class TokenTool(Base):
    """Level 2: which tools inside those servers a token may call."""

    __tablename__ = "token_tools"

    token_id: Mapped[int] = mapped_column(
        ForeignKey("tokens.id", ondelete="CASCADE"), primary_key=True
    )
    tool_id: Mapped[int] = mapped_column(
        ForeignKey("tools.id", ondelete="CASCADE"), primary_key=True
    )


class ParameterInjection(Base):
    """Level 3: values the gateway forces into a tool call before forwarding."""

    __tablename__ = "parameter_injections"
    __table_args__ = (
        UniqueConstraint("token_id", "tool_id", "argument"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    token_id: Mapped[int] = mapped_column(
        ForeignKey("tokens.id", ondelete="CASCADE"), nullable=False
    )
    tool_id: Mapped[int] = mapped_column(
        ForeignKey("tools.id", ondelete="CASCADE"), nullable=False
    )
    argument: Mapped[str] = mapped_column(String(128), nullable=False)
    value: Mapped[Any] = mapped_column(JSON, nullable=False)


class AuditEvent(Base):
    """Permanent audit trail. Raw argument values are never stored."""

    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_started_at", "started_at"),
        Index("ix_audit_events_token_id", "token_id"),
        Index("ix_audit_events_tool_name", "tool_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    token_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    service_slug: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tool_name: Mapped[str] = mapped_column(String(256), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="started", nullable=False)
    denial_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    argument_keys: Mapped[list[str]] = mapped_column(
        JSON, default=list, nullable=False
    )
    requested_argument_hashes: Mapped[dict[str, str]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    effective_argument_hashes: Mapped[dict[str, str] | None] = mapped_column(
        JSON, nullable=True
    )
    started_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, default=utcnow, nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(TIMESTAMP, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)


# ── AI 网关相关枚举值 ───────────────────────────────────────────────
# 统一用 String(16) 存字符串，与现有 risk/status 的存法一致，不引 SQLAlchemy
# Enum 类型（避免迁移里多出带值的枚举类型，也方便以后直接加值）。下面的常量
# 是 Python 侧唯一取值来源，schemas 与后续服务都从这里取。
AI_MODEL_KIND_CHAT = "chat"
AI_MODEL_KIND_EMBEDDING = "embedding"

AI_KEY_PERIOD_DAY = "day"
AI_KEY_PERIOD_MONTH = "month"
AI_KEY_PERIOD_NONE = "none"

GUARDRAIL_SCOPE_REQUEST = "request"
GUARDRAIL_SCOPE_RESPONSE = "response"
GUARDRAIL_SCOPE_BOTH = "both"
GUARDRAIL_ACTION_BLOCK = "block"

PROVIDER_HEALTH_UNKNOWN = "unknown"
PROVIDER_HEALTH_HEALTHY = "healthy"
PROVIDER_HEALTH_UNHEALTHY = "unhealthy"

USAGE_STATUS_STARTED = "started"
USAGE_STATUS_SUCCEEDED = "succeeded"
USAGE_STATUS_FAILED = "failed"
USAGE_STATUS_DENIED = "denied"


class AiProvider(Base):
    """上游厂商 / 中转：对外暴露的模型都来自某个 provider。"""

    __tablename__ = "ai_providers"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    base_url: Mapped[str] = mapped_column(String(512), nullable=False)
    # 上游密钥：加密存储，绝不落明文
    api_key_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    health: Mapped[str] = mapped_column(
        String(16), default=PROVIDER_HEALTH_UNKNOWN, nullable=False
    )
    consecutive_failures: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    last_error: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(TIMESTAMP, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, default=utcnow, onupdate=utcnow, nullable=False
    )


class AiModel(Base):
    """模型注册表：把上游真实模型名映射成对外暴露的 alias。"""

    __tablename__ = "ai_models"
    __table_args__ = (
        UniqueConstraint(
            "provider_id", "provider_model_name", name="uq_ai_models_provider_upstream"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    provider_id: Mapped[int] = mapped_column(
        ForeignKey("ai_providers.id", ondelete="CASCADE"), nullable=False
    )
    provider_model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    alias: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), default=AI_MODEL_KIND_CHAT, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # 每千 token 单价，仅用于成本展示统计，不参与计费
    input_price: Mapped[float | None] = mapped_column(Numeric(12, 6), nullable=True)
    output_price: Mapped[float | None] = mapped_column(Numeric(12, 6), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, default=utcnow, onupdate=utcnow, nullable=False
    )


class AiApiKey(Base):
    """对外分发的 AI Key：库里只存 HMAC 哈希，明文只在创建时返回一次。"""

    __tablename__ = "ai_api_keys"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(TIMESTAMP, nullable=True)
    # 周期 token 配额，null = 不限
    period_token_limit: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    period: Mapped[str] = mapped_column(String(16), default=AI_KEY_PERIOD_NONE, nullable=False)
    # 每分钟请求上限，null = 不限
    rate_limit_rpm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=utcnow, nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(TIMESTAMP, nullable=True)


class AiKeyModel(Base):
    """Key 的模型授权（deny-by-default）：显式点名，不提供"允许全部"开关。"""

    __tablename__ = "ai_key_models"

    key_id: Mapped[int] = mapped_column(
        ForeignKey("ai_api_keys.id", ondelete="CASCADE"), primary_key=True
    )
    model_id: Mapped[int] = mapped_column(
        ForeignKey("ai_models.id", ondelete="CASCADE"), primary_key=True
    )


class AiUsageEvent(Base):
    """请求级明细（审计主表）。原始入参不留存，与现有审计哲学一致。"""

    __tablename__ = "ai_usage_events"
    __table_args__ = (
        Index("ix_ai_usage_events_started_at", "started_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # 快照式冗余：Key 删除后审计仍可读
    key_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    key_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    model_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    model_alias: Mapped[str | None] = mapped_column(String(128), nullable=True)
    provider_slug: Mapped[str | None] = mapped_column(String(32), nullable=True)
    endpoint: Mapped[str] = mapped_column(String(64), nullable=False)
    stream: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default=USAGE_STATUS_STARTED, nullable=False
    )
    denial_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    upstream_status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # token 数是否为估算（流式降级路径），审计上不假装精确
    usage_estimated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # 命中的规则 id + 类别，不存命中原文
    guardrail_hits: Mapped[list | None] = mapped_column(JSON, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    first_token_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=utcnow, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(TIMESTAMP, nullable=True)


class AiUsageDaily(Base):
    """日汇总（配额判定热路径）：按 (key_id, day) 累加，行数极小。"""

    __tablename__ = "ai_usage_daily"

    key_id: Mapped[int] = mapped_column(
        ForeignKey("ai_api_keys.id", ondelete="CASCADE"), primary_key=True
    )
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    requests: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    total_tokens: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)


class GuardrailRule(Base):
    """敏感词护栏规则：首版纯关键词（子串、大小写不敏感），字段留 regex 扩展位。"""

    __tablename__ = "guardrail_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    pattern: Mapped[str] = mapped_column(String(512), nullable=False)
    scope: Mapped[str] = mapped_column(
        String(16), default=GUARDRAIL_SCOPE_REQUEST, nullable=False
    )
    action: Mapped[str] = mapped_column(
        String(16), default=GUARDRAIL_ACTION_BLOCK, nullable=False
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, default=utcnow, onupdate=utcnow, nullable=False
    )