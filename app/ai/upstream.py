"""AI 上游 HTTP 连接池：按 (base_url, api_key) 复用 httpx.AsyncClient。

设计文档 §4.1⑧ / §4.2。同一个 (base_url, api_key) 组合复用同一条长连接，不同
上游（或不同凭证）落到不同 client，避免"串号"。超时拆成连接超时（ai_connect_timeout）
与请求超时（ai_request_timeout）；流式下请求超时也要覆盖整段 SSE，故比连接超时
长很多。

工厂可注入：测试用 httpx.ASGITransport(app=假上游) 的构建函数替换默认实现，
全程不触网。
"""
import asyncio
from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Any

import httpx

from app.core.config import Settings

# 注入工厂签名：(base_url, api_key, settings) -> httpx.AsyncClient
ClientFactory = Callable[[str, str, Settings], httpx.AsyncClient]


def _default_client_factory(
    base_url: str, api_key: str, settings: Settings
) -> httpx.AsyncClient:
    """默认工厂：真实触网。超时拆连接/请求两段，并带上游 Bearer 鉴权。"""
    timeout = httpx.Timeout(
        settings.ai_request_timeout,
        connect=settings.ai_connect_timeout,
    )
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    return httpx.AsyncClient(base_url=base_url, timeout=timeout, headers=headers)


class AiUpstreamPool:
    def __init__(
        self,
        settings: Settings,
        *,
        client_factory: ClientFactory | None = None,
    ) -> None:
        self._settings = settings
        self._factory = client_factory or _default_client_factory
        # key = (base_url, api_key)：凭证不同必须落在不同 client，否则会串号
        self._clients: dict[tuple[str, str], httpx.AsyncClient] = {}
        self._lock = asyncio.Lock()

    async def get_client(self, *, base_url: str, api_key: str) -> httpx.AsyncClient:
        key = (base_url, api_key)
        existing = self._clients.get(key)
        if existing is not None:
            return existing
        # 双检：revision 失效/首次竞争瞬间，避免同 key 并发各建一个 client
        async with self._lock:
            existing = self._clients.get(key)
            if existing is not None:
                return existing
            client = self._factory(base_url, api_key, self._settings)
            self._clients[key] = client
            return client

    async def aclose(self) -> None:
        """关闭所有上游 client（lifespan 关停时调用）。"""
        # 先把引用摘走，避免关闭期间别的协程拿到半死的 client
        clients = list(self._clients.values())
        self._clients.clear()
        for client in clients:
            await client.aclose()

    async def post_json(
        self,
        *,
        base_url: str,
        api_key: str,
        path: str,
        json: Any,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        """非流式 POST JSON，返回完整响应（调用方负责 resp.raise_for_status 或判码）。"""
        client = await self.get_client(base_url=base_url, api_key=api_key)
        merged = self._auth_headers(api_key, headers)
        return await client.post(path, json=json, headers=merged)

    @asynccontextmanager
    async def stream_sse(
        self,
        *,
        base_url: str,
        api_key: str,
        path: str,
        json: Any,
        headers: dict[str, str] | None = None,
    ):
        """流式 POST：以上下文管理器形式暴露一个可遍历字节流的 httpx.Response。

        调用方 `async with pool.stream_sse(...) as resp: async for chunk in resp.aiter_bytes()`。
        离开 with 块时自动关闭底层流。
        """
        client = await self.get_client(base_url=base_url, api_key=api_key)
        merged = self._auth_headers(api_key, headers)
        async with client.stream("POST", path, json=json, headers=merged) as resp:
            yield resp

    @staticmethod
    def _auth_headers(
        api_key: str, extra: dict[str, str] | None
    ) -> dict[str, str]:
        # 便捷方法统一补 Bearer；显式传入的 headers 可覆盖（如加自定义头）
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        if extra:
            headers.update(extra)
        return headers
