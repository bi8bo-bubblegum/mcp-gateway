import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.concurrency import KeyedLocks
from app.core.config import Settings
from app.core.security import (
    TokenHasher,
    generate_opaque_token,
    token_display_prefix,
)
from app.db.base import utcnow
from app.db.models import (
    ParameterInjection,
    Service,
    Token,
    TokenService as TokenServiceLink,
    TokenTool,
    Tool,
)
from app.schemas.token import TokenCreate, TokenPolicyUpdate
from app.services.revision import RevisionStore, bump_revision


class TokenServiceError(Exception):
    """Raised for invalid or inconsistent token policy configuration."""


@dataclass(frozen=True)
class TokenSnapshot:
    """Immutable policy view used on the hot request path."""

    id: int
    name: str
    allow_high_risk: bool
    visible_service_ids: frozenset[int]
    allowed_tool_ids: frozenset[int]
    injections: Mapping[int, Mapping[str, Any]]


InjectionValues = Mapping[tuple[int, str], Any]


@dataclass
class _CacheEntry:
    snapshot: TokenSnapshot
    revision: int
    expires_at: float


def value_matches_schema(prop: Mapping[str, Any], value: Any) -> bool:
    """Minimal JSON Schema check for injected values.

    Only `type` and `enum` are enforced. The goal is to catch obviously broken
    configuration, not to reimplement a full validator.
    """
    allowed = prop.get("enum")
    if allowed is not None and value not in allowed:
        return False
    declared = prop.get("type")
    if declared is None:
        return True
    names = [declared] if isinstance(declared, str) else list(declared)
    checks = {
        "string": lambda v: isinstance(v, str),
        "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
        "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
        "boolean": lambda v: isinstance(v, bool),
        "array": lambda v: isinstance(v, list),
        "object": lambda v: isinstance(v, dict),
        "null": lambda v: v is None,
    }
    return any(checks.get(name, lambda v: True)(value) for name in names)


class TokenService:
    def __init__(
        self,
        *,
        settings: Settings,
        hasher: TokenHasher,
        revisions: RevisionStore,
    ) -> None:
        self._settings = settings
        self._hasher = hasher
        self._revisions = revisions
        self._by_hash: dict[str, _CacheEntry] = {}
        self._by_id: dict[int, _CacheEntry] = {}
        self._locks = KeyedLocks()

    # -------------------------------------------------------- verification

    async def verify(self, raw_token: str) -> TokenSnapshot | None:
        """Resolve a bearer token to its current policy, or None if unusable."""
        if not raw_token:
            return None
        token_hash = self._hasher.hash_token(raw_token)
        revision = await self._revisions.current()
        cached = self._by_hash.get(token_hash)
        if cached is not None and self._fresh(cached, revision):
            return cached.snapshot

        # 缓存未命中时加锁：policy_cache_ttl 到期那一刻，同一 token 的并发
        # 请求否则会各自查库（一次 verify 是 1 条 token + 3 条策略查询）。
        # 锁表有上界，不会被客户端乱编的 token 撑爆。
        async with self._locks.hold(f"hash:{token_hash}"):
            revision = await self._revisions.current()
            cached = self._by_hash.get(token_hash)
            if cached is not None and self._fresh(cached, revision):
                return cached.snapshot  # 等锁期间已被其他协程填好

            from app.db.session import session_scope

            async with session_scope() as session:
                result = await session.execute(
                    select(Token).where(Token.token_hash == token_hash)
                )
                token = result.scalar_one_or_none()
                if token is None or not token.enabled or token.revoked_at is not None:
                    self._by_hash.pop(token_hash, None)
                    return None
                snapshot = await self._build_snapshot(session, token)

            entry = _CacheEntry(
                snapshot=snapshot,
                revision=revision,
                expires_at=time.monotonic() + self._settings.policy_cache_ttl,
            )
            self._by_hash[token_hash] = entry
            self._by_id[snapshot.id] = entry
            return snapshot

    async def snapshot_by_id(self, token_id: int) -> TokenSnapshot | None:
        revision = await self._revisions.current()
        cached = self._by_id.get(token_id)
        if cached is not None and self._fresh(cached, revision):
            return cached.snapshot

        async with self._locks.hold(f"id:{token_id}"):
            revision = await self._revisions.current()
            cached = self._by_id.get(token_id)
            if cached is not None and self._fresh(cached, revision):
                return cached.snapshot  # 等锁期间已被其他协程填好

            from app.db.session import session_scope

            async with session_scope() as session:
                token = await session.get(Token, token_id)
                if token is None or not token.enabled or token.revoked_at is not None:
                    return None
                snapshot = await self._build_snapshot(session, token)

            entry = _CacheEntry(
                snapshot=snapshot,
                revision=revision,
                expires_at=time.monotonic() + self._settings.policy_cache_ttl,
            )
            self._by_id[token_id] = entry
            return snapshot

    def _fresh(self, entry: _CacheEntry, revision: int) -> bool:
        return entry.revision == revision and entry.expires_at > time.monotonic()

    def invalidate(self, token_id: int | None = None) -> None:
        if token_id is None:
            self._by_hash.clear()
            self._by_id.clear()
            return
        self._by_id.pop(token_id, None)
        for key, entry in list(self._by_hash.items()):
            if entry.snapshot.id == token_id:
                del self._by_hash[key]

    # -------------------------------------------------------------- admin

    async def create(
        self, session: AsyncSession, payload: TokenCreate
    ) -> tuple[Token, str]:
        visible = set(payload.visible_service_ids)
        allowed = set(payload.allowed_tool_ids)
        injections = {
            (item.tool_id, item.argument): item.value
            for item in payload.parameter_injections
        }
        await self._validate_policy(
            session,
            allow_high_risk=payload.allow_high_risk,
            visible_service_ids=visible,
            allowed_tool_ids=allowed,
            injections=injections,
        )

        raw_token = generate_opaque_token()
        token = Token(
            name=payload.name,
            token_hash=self._hasher.hash_token(raw_token),
            token_prefix=token_display_prefix(raw_token),
            enabled=True,
            allow_high_risk=payload.allow_high_risk,
        )
        session.add(token)
        await session.flush()
        await self._write_policy(
            session,
            token.id,
            visible_service_ids=visible,
            allowed_tool_ids=allowed,
            injections=injections,
        )
        await bump_revision(session)
        await session.commit()
        self.invalidate()
        return token, raw_token

    async def update_policy(
        self, session: AsyncSession, token_id: int, payload: TokenPolicyUpdate
    ) -> Token:
        token = await self._require_token(session, token_id)

        visible = (
            set(payload.visible_service_ids)
            if payload.visible_service_ids is not None
            else await self._current_service_ids(session, token_id)
        )
        allowed = (
            set(payload.allowed_tool_ids)
            if payload.allowed_tool_ids is not None
            else await self._current_tool_ids(session, token_id)
        )
        injections: dict[tuple[int, str], Any] = (
            {
                (item.tool_id, item.argument): item.value
                for item in payload.parameter_injections
            }
            if payload.parameter_injections is not None
            else dict(await self._current_injections(session, token_id))
        )
        allow_high_risk = (
            payload.allow_high_risk
            if payload.allow_high_risk is not None
            else token.allow_high_risk
        )

        await self._validate_policy(
            session,
            allow_high_risk=allow_high_risk,
            visible_service_ids=visible,
            allowed_tool_ids=allowed,
            injections=injections,
        )

        if payload.name is not None:
            token.name = payload.name
        if payload.enabled is not None:
            token.enabled = payload.enabled
        token.allow_high_risk = allow_high_risk

        await self._write_policy(
            session,
            token_id,
            visible_service_ids=visible,
            allowed_tool_ids=allowed,
            injections=injections,
        )
        await bump_revision(session)
        await session.commit()
        self.invalidate(token_id)
        await session.refresh(token)
        return token

    async def revoke(self, session: AsyncSession, token_id: int) -> Token:
        token = await self._require_token(session, token_id)
        token.enabled = False
        token.revoked_at = utcnow()
        await bump_revision(session)
        await session.commit()
        self.invalidate(token_id)
        await session.refresh(token)
        return token

    async def get(self, session: AsyncSession, token_id: int) -> Token:
        return await self._require_token(session, token_id)

    async def list_tokens(self, session: AsyncSession) -> Sequence[Token]:
        result = await session.execute(select(Token).order_by(Token.id))
        return list(result.scalars())

    async def policy_detail(
        self, session: AsyncSession, token_id: int
    ) -> tuple[list[int], list[int], list[ParameterInjection]]:
        visible = sorted(await self._current_service_ids(session, token_id))
        allowed = sorted(await self._current_tool_ids(session, token_id))
        result = await session.execute(
            select(ParameterInjection)
            .where(ParameterInjection.token_id == token_id)
            .order_by(ParameterInjection.id)
        )
        return visible, allowed, list(result.scalars())

    # -------------------------------------------------------------- private

    async def _require_token(self, session: AsyncSession, token_id: int) -> Token:
        token = await session.get(Token, token_id)
        if token is None:
            raise TokenServiceError(f"token {token_id} not found")
        return token

    async def _current_service_ids(
        self, session: AsyncSession, token_id: int
    ) -> set[int]:
        result = await session.execute(
            select(TokenServiceLink.service_id).where(
                TokenServiceLink.token_id == token_id
            )
        )
        return {int(row) for row in result.scalars()}

    async def _current_tool_ids(
        self, session: AsyncSession, token_id: int
    ) -> set[int]:
        result = await session.execute(
            select(TokenTool.tool_id).where(TokenTool.token_id == token_id)
        )
        return {int(row) for row in result.scalars()}

    async def _current_injections(
        self, session: AsyncSession, token_id: int
    ) -> dict[tuple[int, str], Any]:
        result = await session.execute(
            select(ParameterInjection).where(
                ParameterInjection.token_id == token_id
            )
        )
        return {(row.tool_id, row.argument): row.value for row in result.scalars()}

    async def _build_snapshot(self, session: AsyncSession, token: Token) -> TokenSnapshot:
        visible = await self._current_service_ids(session, token.id)
        allowed = await self._current_tool_ids(session, token.id)
        raw = await self._current_injections(session, token.id)

        grouped: dict[int, dict[str, Any]] = {}
        for (tool_id, argument), value in raw.items():
            grouped.setdefault(tool_id, {})[argument] = value

        return TokenSnapshot(
            id=token.id,
            name=token.name,
            allow_high_risk=token.allow_high_risk,
            visible_service_ids=frozenset(visible),
            allowed_tool_ids=frozenset(allowed),
            injections=MappingProxyType(
                {key: MappingProxyType(dict(value)) for key, value in grouped.items()}
            ),
        )

    async def _write_policy(
        self,
        session: AsyncSession,
        token_id: int,
        *,
        visible_service_ids: set[int],
        allowed_tool_ids: set[int],
        injections: InjectionValues,
    ) -> None:
        await session.execute(
            delete(TokenServiceLink).where(TokenServiceLink.token_id == token_id)
        )
        await session.execute(
            delete(TokenTool).where(TokenTool.token_id == token_id)
        )
        await session.execute(
            delete(ParameterInjection).where(ParameterInjection.token_id == token_id)
        )
        await session.flush()

        session.add_all(
            [
                TokenServiceLink(token_id=token_id, service_id=service_id)
                for service_id in sorted(visible_service_ids)
            ]
        )
        session.add_all(
            [
                TokenTool(token_id=token_id, tool_id=tool_id)
                for tool_id in sorted(allowed_tool_ids)
            ]
        )
        session.add_all(
            [
                ParameterInjection(
                    token_id=token_id, tool_id=tool_id, argument=argument, value=value
                )
                for (tool_id, argument), value in sorted(injections.items())
            ]
        )

    async def _validate_policy(
        self,
        session: AsyncSession,
        *,
        allow_high_risk: bool,
        visible_service_ids: set[int],
        allowed_tool_ids: set[int],
        injections: InjectionValues,
    ) -> None:
        if visible_service_ids:
            result = await session.execute(
                select(Service.id).where(Service.id.in_(visible_service_ids))
            )
            missing = visible_service_ids - {int(row) for row in result.scalars()}
            if missing:
                raise TokenServiceError(f"unknown service ids: {sorted(missing)}")

        tools: dict[int, Tool] = {}
        if allowed_tool_ids:
            result = await session.execute(
                select(Tool).where(Tool.id.in_(allowed_tool_ids))
            )
            tools = {tool.id: tool for tool in result.scalars()}
            missing = allowed_tool_ids - set(tools)
            if missing:
                raise TokenServiceError(f"unknown tool ids: {sorted(missing)}")

        for tool in tools.values():
            if tool.service_id not in visible_service_ids:
                raise TokenServiceError(
                    f"tool {tool.id} belongs to a service that is not visible to this token"
                )
            if tool.risk == "high" and not allow_high_risk:
                raise TokenServiceError(
                    f"tool {tool.id} is high risk; enable allow_high_risk first"
                )

        for (tool_id, argument), value in injections.items():
            tool = tools.get(tool_id)
            if tool is None:
                raise TokenServiceError(
                    f"parameter injection targets tool {tool_id}, which is not allowed"
                )
            properties = (tool.input_schema or {}).get("properties") or {}
            prop = properties.get(argument)
            if prop is None:
                raise TokenServiceError(
                    f"tool {tool_id} has no argument '{argument}' to inject"
                )
            if not value_matches_schema(prop, value):
                raise TokenServiceError(
                    f"value for '{argument}' does not match the tool schema"
                )