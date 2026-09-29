import asyncio
import logging
import mcp_types
import time

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Protocol
from fastmcp.client import Client
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.tools import ToolResult

from app.core.security import SecretBox

logger = logging.getLogger(__name__)

TOOL_NAME_SEPARATOR = "__"
# 与 app/db/models.py 中 tools.upstream_name / tools.effective_name 的列宽一致
MAX_UPSTREAM_NAME_LENGTH = 128
MAX_EFFECTIVE_NAME_LENGTH = 256
DEFAULT_POOL_SIZE = 4
# 池满时等待归还的重判间隔：等这么久还没等到，就回循环顶部重新判断
# 是否该新建连接（否则"长时间空闲后来一批并发"会退化成单连接串行）。
POOL_WAIT_RECHECK_SECONDS = 0.5

def effective_tool_name(service_slug: str, upstream_name: str) -> str:
    return f"{service_slug}{TOOL_NAME_SEPARATOR}{upstream_name}"

def tool_name_problem(service_slug: str, upstream_name: str) -> str | None:
    """检查上游工具名能不能安全落库，返回拒绝原因；None 表示可用。

    上游是别人的服务，工具名的长度和内容都不受我们控制，而它会直接写进
    tools.effective_name（唯一索引 + String(256)）和 tools.upstream_name
    （String(128)）。不校验的话，一个超长名字就能让整次刷新的写入事务在
    MySQL 严格模式下报 1406 而整体失败；名字里带分隔符则会让
    split_effective_name 解析出错误的服务。
    """
    if not upstream_name:
        return "工具名为空"
    if TOOL_NAME_SEPARATOR in upstream_name:
        return f"工具名包含保留分隔符 {TOOL_NAME_SEPARATOR!r}"
    if len(upstream_name) > MAX_UPSTREAM_NAME_LENGTH:
        return f"工具名 {len(upstream_name)} 字符，超过 {MAX_UPSTREAM_NAME_LENGTH} 上限"
    combined = len(service_slug) + len(TOOL_NAME_SEPARATOR) + len(upstream_name)
    if combined > MAX_EFFECTIVE_NAME_LENGTH:
        return f"加上服务前缀后 {combined} 字符，超过 {MAX_EFFECTIVE_NAME_LENGTH} 上限"
    return None

def split_effective_name(name: str) -> tuple[str, str] | None:
    slug, separator, upstream = name.partition(TOOL_NAME_SEPARATOR)
    if not separator or not slug or not upstream:
        return None
    return slug, upstream

@dataclass(frozen=True)
class UpstreamAuth:
    # 明文凭证排除出 repr：headers 里通常也放 API key，同样不能进日志
    bearer_token: str | None = field(default=None, repr=False)
    headers: dict[str, str] = field(default_factory=dict, repr=False)

    def __repr__(self) -> str:
        """只表明凭证是否配置、有哪些 header 名，不暴露任何值。

        排查"上游 401 是不是没配凭证"时要能一眼看出来，所以不能不输出，
        但输出了就等于把密钥写进日志。
        """
        bearer = "set" if self.bearer_token else "none"
        return f"UpstreamAuth(bearer_token={bearer}, headers={sorted(self.headers)})"

    @classmethod
    def from_payload(cls, payload: dict[str, Any] | None) -> "UpstreamAuth":
        payload = payload or {}
        raw_headers = payload.get("headers") or {}
        headers = {str(k): str(v) for k, v in raw_headers.items()}
        bearer = payload.get("bearer_token")
        return cls(
            bearer_token=str(bearer) if bearer else None,
            headers=headers
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "bearer_token": self.bearer_token,
            "headers": dict(self.headers)
        }

@dataclass(frozen=True)
class UpstreamToolSpec:
    name: str
    description: str | None
    input_schema: dict[str, Any]

class UpstreamClientFactory(Protocol):
    def build(self, *, url: str, auth: UpstreamAuth, timeout: float) -> Client[Any]:
        ...

class StreamableHttpClientFactory:
    def build(self, *, url: str, auth: UpstreamAuth, timeout: float) -> Client[Any]:
        transport = StreamableHttpTransport(
            url=url,
            headers=dict(auth.headers),
            auth=auth.bearer_token
        )
        return Client(
            transport,
            name="gateway-upstream",
            timeout=timeout,
            init_timeout=timeout
        )

def decrypt_auth(secret_box: SecretBox, ciphertext: str | None) -> UpstreamAuth:
    """上游凭证解密的唯一实现，RuntimeRegistry 与 ServiceManager 共用。"""
    if not ciphertext:
        return UpstreamAuth()
    return UpstreamAuth.from_payload(secret_box.decrypt(ciphertext))

async def discover_tools(factory: UpstreamClientFactory, *, url: str, auth: UpstreamAuth, timeout: float) -> list[UpstreamToolSpec]:
    # 发现流程是一次性的，而且发现之后凭证/URL 往往马上要改：
    # 刻意不走连接池，免得把坏凭证的长连接留在池里污染后续调用。
    client = factory.build(url=url, auth=auth, timeout=timeout)
    async with asyncio.timeout(timeout):
        async with client:
            tools = await client.list_tools()
    return [UpstreamToolSpec(name=tool.name, description=tool.description, input_schema=dict(tool.input_schema or {})) for tool in tools]

PoolKey = tuple[str, str | None, tuple[tuple[str, str], ...], float]

def pool_key(*, url: str, auth: UpstreamAuth, timeout: float) -> PoolKey:
    """同一 URL 但凭证不同必须落在不同的池，否则会串号。"""
    return url, auth.bearer_token, tuple(sorted(auth.headers.items())), timeout

class _Slot:
    """池中的一个连接槽，自己持有退出栈。"""

    def __init__(self, factory: UpstreamClientFactory, *, url: str, auth: UpstreamAuth, timeout: float) -> None:
        self._factory = factory
        self._url = url
        self._auth = auth
        self._timeout = timeout
        self._stack: AsyncExitStack | None = None
        self.client: Client[Any] | None = None
        self.idle_since = time.monotonic()

    async def open(self) -> None:
        stack = AsyncExitStack()
        client = self._factory.build(url=self._url, auth=self._auth, timeout=self._timeout)
        try:
            await stack.enter_async_context(client)
        except BaseException:
            await stack.aclose()
            raise
        self._stack = stack
        self.client = client

    async def close(self) -> None:
        stack, self._stack = self._stack, None
        self.client = None
        if stack is None:
            return
        try:
            await stack.aclose()
        except Exception:
            logger.warning("关闭上游连接失败", exc_info=True)

class _UpstreamPool:
    """一个 (url, 凭证, 超时) 组合对应的连接池。"""

    def __init__(
        self,
        *,
        factory: UpstreamClientFactory,
        url: str,
        auth: UpstreamAuth,
        timeout: float,
        size: int,
        max_slot_idle: float,
    ) -> None:
        self._factory = factory
        self._url = url
        self._auth = auth
        self._timeout = timeout
        self._size = size
        self._max_slot_idle = max_slot_idle
        self._idle: asyncio.Queue[_Slot] = asyncio.Queue()
        self._live = 0
        self._lock = asyncio.Lock()
        self._closed = False
        self.last_used = time.monotonic()

    @property
    def all_idle(self) -> bool:
        """所有存活连接都已归还，可以整体回收。"""
        return self._idle.qsize() >= self._live

    async def acquire(self) -> _Slot:
        while True:
            async with self._lock:
                if self._closed:
                    raise RuntimeError("上游连接池已关闭")
                if not self._idle.empty():
                    slot: _Slot | None = self._idle.get_nowait()
                    reserve = False
                else:
                    slot = None
                    reserve = self._live < self._size
                    if reserve:
                        self._live += 1

            if slot is not None:
                if self._max_slot_idle > 0 and time.monotonic() - slot.idle_since > self._max_slot_idle:
                    # 空闲太久的长连接可能已被上游单方面断开。复用它的结果
                    # 是让这一个请求白白失败，不如丢掉重连：代价是一次握手，
                    # 换来的是"长时间空闲后的第一个请求"不会莫名报错。
                    await self.discard(slot)
                    continue
                self.last_used = time.monotonic()
                return slot

            if reserve:
                return await self._open()

            try:
                slot = await asyncio.wait_for(
                    self._idle.get(), timeout=POOL_WAIT_RECHECK_SECONDS
                )
            except TimeoutError:
                # 一直没等到归还：回循环顶部重新判断能否新建连接
                continue
            if self._closed:
                await slot.close()
                async with self._lock:
                    self._live -= 1
                raise RuntimeError("上游连接池已关闭")
            self.last_used = time.monotonic()
            return slot

    async def _open(self) -> _Slot:
        slot = _Slot(self._factory, url=self._url, auth=self._auth, timeout=self._timeout)
        try:
            await slot.open()
        except BaseException:
            async with self._lock:
                self._live -= 1
            raise
        self.last_used = slot.idle_since = time.monotonic()
        return slot

    async def release(self, slot: _Slot) -> None:
        self.last_used = time.monotonic()
        slot.idle_since = time.monotonic()
        if self._closed:
            await slot.close()
            async with self._lock:
                self._live -= 1
            return
        self._idle.put_nowait(slot)

    async def discard(self, slot: _Slot) -> None:
        """连接可能已被污染或断开：关掉并把容量让出来。"""
        await slot.close()
        async with self._lock:
            self._live -= 1

    async def close(self) -> None:
        async with self._lock:
            self._closed = True
        while True:
            try:
                slot = self._idle.get_nowait()
            except asyncio.QueueEmpty:
                break
            await slot.close()
            async with self._lock:
                self._live -= 1

class UpstreamClientPool:
    """按 (url, 凭证, 超时) 复用上游 MCP Client。

    每次调用都新建 Client，意味着一次完整的 MCP initialize 握手加一次
    TCP/TLS 建连；这里用固定大小的池把长连接留住。
    """

    def __init__(
        self,
        factory: UpstreamClientFactory,
        *,
        size: int = DEFAULT_POOL_SIZE,
        max_slot_idle: float = 60.0,
    ) -> None:
        self._factory = factory
        self._size = size
        self._max_slot_idle = max_slot_idle
        self._pools: dict[PoolKey, _UpstreamPool] = {}
        self._lock = asyncio.Lock()

    @asynccontextmanager
    async def acquire(self, *, url: str, auth: UpstreamAuth, timeout: float) -> AsyncIterator[Client[Any]]:
        key = pool_key(url=url, auth=auth, timeout=timeout)
        pool = await self._pool(key, url=url, auth=auth, timeout=timeout)
        slot = await pool.acquire()
        try:
            yield slot.client
        except BaseException:
            # 调用失败（尤其是被取消）后连接状态未知，丢弃重建，
            # 不把一个可能半死的连接还给下一个请求。
            await pool.discard(slot)
            raise
        await pool.release(slot)

    async def _pool(self, key: PoolKey, *, url: str, auth: UpstreamAuth, timeout: float) -> _UpstreamPool:
        pool = self._pools.get(key)
        if pool is not None:
            return pool
        async with self._lock:
            pool = self._pools.get(key)
            if pool is None:
                pool = _UpstreamPool(
                    factory=self._factory,
                    url=url,
                    auth=auth,
                    timeout=timeout,
                    size=self._size,
                    max_slot_idle=self._max_slot_idle,
                )
                self._pools[key] = pool
            return pool

    async def reap(self, *, max_idle_seconds: float) -> None:
        """回收长时间全空闲的池。

        典型来源：服务被删除，或 URL/凭证被改过之后留下的旧 key。
        刻意不用"当前快照里的服务集合"做白名单式清理——不健康的服务会暂时
        不在快照里，那样会把它们的连接误杀、造成反复重连。
        """
        now = time.monotonic()
        async with self._lock:
            stale = [
                key for key, pool in self._pools.items()
                if pool.all_idle and now - pool.last_used > max_idle_seconds
            ]
            pools = [self._pools.pop(key) for key in stale]
        for pool in pools:
            await pool.close()

    async def aclose(self) -> None:
        async with self._lock:
            pools = list(self._pools.values())
            self._pools.clear()
        for pool in pools:
            await pool.close()

async def call_upstream_tool(
        pool: UpstreamClientPool,
        *,
        url: str,
        auth: UpstreamAuth,
        upstream_name: str,
        arguments: dict[str, Any],
        timeout: float,
) -> ToolResult:
    async with pool.acquire(url=url, auth=auth, timeout=timeout) as client:
        async with asyncio.timeout(timeout):
            result = await client.call_tool_mcp(upstream_name, arguments)
    content = list(result.content or [])
    if not content and result.structured_content is None:
        content = [mcp_types.TextContent(type="text", text="")]
    return ToolResult(
        content=content,
        structured_content=result.structured_content,
        is_error=bool(result.is_error)
    )
