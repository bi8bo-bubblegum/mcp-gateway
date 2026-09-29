import time
from collections import OrderedDict
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


class _NegativeCache:
    """无效 token 的短期负缓存，挡掉伪造 token 与失效 token 的重试风暴。

    没有它时每个无效 token 都要查一次库。伪造 token 是攻击者完全可控的输入，
    1000 req/s 的垃圾流量就是 1000 次查询/s，连接池被占满后正常请求只能在
    pool_timeout 上排队，最后拿到 503。

    key 直接来自客户端，所以必须有上界，否则它自己就是内存放大点——和
    KeyedLocks 是同一类问题。过期时间在写入时固定、命中不延长，避免攻击者
    靠持续请求把某条目永久钉住。

    条目同时绑定 revision：任何配置变更都会让旧判定作废，语义与正向缓存一致。
    """

    def __init__(self, *, maxsize: int, ttl: float) -> None:
        self._maxsize = maxsize
        self._ttl = ttl
        self._entries: OrderedDict[str, tuple[int, float]] = OrderedDict()

    def hit(self, key: str, revision: int) -> bool:
        """命中且未过期返回 True；过期或 revision 不符则顺手清掉。"""
        entry = self._entries.get(key)
        if entry is None:
            return False
        entry_revision, expires_at = entry
        if entry_revision != revision or expires_at <= time.monotonic():
            del self._entries[key]
            return False
        self._entries.move_to_end(key)
        return True

    def add(self, key: str, revision: int) -> None:
        self._entries[key] = (revision, time.monotonic() + self._ttl)
        self._entries.move_to_end(key)
        while len(self._entries) > self._maxsize:
            self._entries.popitem(last=False)

    def clear(self) -> None:
        self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)


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


def resolve_injection_target(
    schema: Mapping[str, Any] | None, argument: str
) -> tuple[tuple[str, ...], Mapping[str, Any]] | None:
    """把注入键解析成 (参数路径, 该参数的 schema 定义)，解析不出返回 None。

    先按顶层参数名精确匹配，这样参数名里本来带点的工具不会被误拆成路径；
    匹配不到再按点号拆成嵌套路径，逐层在 `properties` 里查证，任一层缺失即失败。
    """
    properties = (schema or {}).get("properties") or {}
    if argument in properties:
        prop = properties[argument]
        return ((argument,), prop) if isinstance(prop, Mapping) else None

    parts = argument.split(".")
    if len(parts) < 2 or any(not part for part in parts):
        return None

    # 合成一个根节点，让每一层都走同样的 "取 properties 再取名字" 逻辑
    node: Any = {"properties": properties}
    for part in parts:
        props = node.get("properties") if isinstance(node, Mapping) else None
        if not isinstance(props, Mapping):
            return None
        node = props.get(part)
        if not isinstance(node, Mapping):
            return None
    return tuple(parts), node


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
        self._denied = _NegativeCache(
            maxsize=settings.policy_negative_cache_size,
            ttl=settings.policy_negative_cache_ttl,
        )

    # -------------------------------------------------------- verification

    async def verify(self, raw_token: str) -> TokenSnapshot | None:
        """Resolve a bearer token to its current policy, or None if unusable."""
        if not raw_token:
            return None
        token_hash = self._hasher.hash_token(raw_token)
        revision = await self._revisions.current()
        if self._denied.hit(token_hash, revision):
            return None
        cached = self._by_hash.get(token_hash)
        if cached is not None and self._fresh(cached, revision):
            return cached.snapshot

        # 缓存未命中时加锁：policy_cache_ttl 到期那一刻，同一 token 的并发
        # 请求否则会各自查库（一次 verify 是 1 条 token + 3 条策略查询）。
        # 锁表有上界，不会被客户端乱编的 token 撑爆。
        async with self._locks.hold(f"hash:{token_hash}"):
            revision = await self._revisions.current()
            if self._denied.hit(token_hash, revision):
                return None
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
                    self._denied.add(token_hash, revision)
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
        # 负缓存的键是哈希，按 token_id 反查不到，而这里刚发生了写操作、
        # 任何"无效"判定都不可信，所以整体清掉。上界只有几千条，admin 写操作
        # 又都是人工触发的，清空的代价可以忽略。
        self._denied.clear()
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
            raise TokenServiceError(f"令牌 {token_id} 不存在")
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
                raise TokenServiceError(f"以下服务不存在：{sorted(missing)}")

        tools: dict[int, Tool] = {}
        if allowed_tool_ids:
            result = await session.execute(
                select(Tool).where(Tool.id.in_(allowed_tool_ids))
            )
            tools = {tool.id: tool for tool in result.scalars()}
            missing = allowed_tool_ids - set(tools)
            if missing:
                raise TokenServiceError(f"以下工具不存在：{sorted(missing)}")

        for tool in tools.values():
            if tool.service_id not in visible_service_ids:
                raise TokenServiceError(
                    f"工具 {tool.id} 所在服务不在「可见服务」中，请先勾选对应服务"
                )
            if tool.risk == "high" and not allow_high_risk:
                raise TokenServiceError(
                    f"工具 {tool.id} 为高风险，请先打开「允许调用高风险工具」开关"
                )

        by_tool: dict[int, list[tuple[tuple[str, ...], str]]] = {}
        for (tool_id, argument), value in injections.items():
            tool = tools.get(tool_id)
            if tool is None:
                raise TokenServiceError(
                    f"注入参数指向的工具 {tool_id} 不在允许列表中"
                )
            target = resolve_injection_target(tool.input_schema, argument)
            if target is None:
                raise TokenServiceError(
                    f"工具 {tool_id} 不存在参数 '{argument}'，无法注入"
                )
            path, prop = target
            if not value_matches_schema(prop, value):
                raise TokenServiceError(
                    f"参数 '{argument}' 的值不符合该工具的 Schema 定义"
                )
            by_tool.setdefault(tool_id, []).append((path, argument))

        # 同一工具上，一个注入键是另一个的前缀时（如 request 与 request.phones），
        # 是先整体覆盖再局部覆盖、还是反过来，没有唯一合理答案。拒绝掉，
        # 免得配出一条自己都说不清最终生效值的规则。
        for tool_id, entries in by_tool.items():
            for index, (path, argument) in enumerate(entries):
                for other_path, other in entries[index + 1 :]:
                    shorter, longer = sorted((path, other_path), key=len)
                    if longer[: len(shorter)] == shorter:
                        raise TokenServiceError(
                            f"工具 {tool_id} 的注入路径 '{argument}' 与 '{other}' "
                            "重叠，请只保留更具体的一条"
                        )