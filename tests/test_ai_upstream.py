"""上游连接池测试：同 key 复用、不同 key 重建、可注入假工厂跑通非流式 + 流式。

设计文档 §4.1⑧ / §4.2。key = (base_url, api_key) → httpx.AsyncClient，超时取
settings.ai_request_timeout / ai_connect_timeout；工厂可注入（测试用 ASGITransport
包假上游 app，全程不触网）。
"""
import httpx
import pytest

from app.ai.upstream import AiUpstreamPool
from tests.fakes.openai_upstream import make_upstream_app


def _fake_factory(app):
    """注入假上游：用 ASGITransport 包成一个 httpx client，不触网。"""

    def factory(base_url: str, api_key: str, settings):  # noqa: ANN001
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://upstream"
        )

    return factory


async def test_client_reused_for_same_key(settings):
    # 同 (base_url, api_key) → 复用同一个 client，工厂只被调一次
    calls = []

    def factory(bu, ak, s):  # noqa: ANN001
        calls.append((bu, ak))
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=make_upstream_app()),
            base_url="http://upstream",
        )

    pool = AiUpstreamPool(settings, client_factory=factory)
    c1 = await pool.get_client(base_url="http://u", api_key="same")
    c2 = await pool.get_client(base_url="http://u", api_key="same")
    assert c1 is c2
    assert len(calls) == 1
    await pool.aclose()


async def test_client_rebuilt_for_different_key(settings):
    # 不同 api_key → 不同 client，工厂被调两次
    calls = []

    def factory(bu, ak, s):  # noqa: ANN001
        calls.append(ak)
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=make_upstream_app()),
            base_url="http://upstream",
        )

    pool = AiUpstreamPool(settings, client_factory=factory)
    await pool.get_client(base_url="http://u", api_key="a")
    await pool.get_client(base_url="http://u", api_key="b")
    assert len(calls) == 2
    await pool.aclose()


async def test_runs_through_fake_upstream_non_stream_and_stream(settings):
    # 同 key 下跑通一次非流式 + 一次流式，全程不触网
    app = make_upstream_app()
    pool = AiUpstreamPool(settings, client_factory=_fake_factory(app))

    # 非流式：响应体透传，usage 与假上游一致
    resp = await pool.post_json(
        base_url="http://upstream",
        api_key="k",
        path="/v1/chat/completions",
        json={"model": "gpt", "messages": [], "stream": False},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["usage"]["prompt_tokens"] == 5
    assert data["usage"]["total_tokens"] == 12

    # 流式：逐字节可读，body 含 SSE 数据
    async with pool.stream_sse(
        base_url="http://upstream",
        api_key="k",
        path="/v1/chat/completions",
        json={"model": "gpt", "messages": [], "stream": True},
    ) as sresp:
        assert sresp.status_code == 200
        chunks = []
        async for chunk in sresp.aiter_bytes():
            chunks.append(chunk)
        body = b"".join(chunks)
        assert b"data:" in body
        assert b"[DONE]" in body

    await pool.aclose()


async def test_post_json_sends_bearer_auth(settings):
    # 便捷方法应自动带 Authorization: Bearer <api_key>
    app = make_upstream_app()

    async def capture(request):  # 校验上游确实收到 Bearer
        return request

    from fastapi import FastAPI, Request

    probe = FastAPI()

    @probe.post("/v1/chat/completions")
    async def chat(request: Request):
        return {"got_auth": request.headers.get("authorization")}

    pool = AiUpstreamPool(settings, client_factory=_fake_factory(probe))
    resp = await pool.post_json(
        base_url="http://upstream",
        api_key="secret-key",
        path="/v1/chat/completions",
        json={"model": "gpt", "stream": False},
    )
    assert resp.json()["got_auth"] == "Bearer secret-key"
    await pool.aclose()
