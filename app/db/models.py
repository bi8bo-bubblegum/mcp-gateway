from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    ForeignKey,
    Index,
    Integer,
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