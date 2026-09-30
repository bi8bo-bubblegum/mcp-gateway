"""流式 chat/completions 端到端：SSE 透传、include_usage 注入、首 token 时延、记账。

断连（客户端中途关流）的记账行为已由 tests/test_ai_streaming.py 的单测覆盖
（test_disconnect_marks_cancelled），这里覆盖 HTTP 层的流式正向路径与护栏。
"""
import json

from app.services.ai_usage_service import AiUsageService


def _auth(raw: str) -> dict:
    return {"Authorization": f"Bearer {raw}"}


def _stream_body(model: str = "gpt-4o-mini", content: str = "你好") -> dict:
    return {"model": model, "messages": [{"role": "user", "content": content}], "stream": True}


async def test_stream_success(client, ai_seed, upstream_calls):
    seed = await ai_seed()

    resp = await client.post(
        "/v1/chat/completions", json=_stream_body(), headers=_auth(seed["raw"])
    )

    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]
    # chunk 原样透传（含结束标记）
    assert '"content": "Hello"' in resp.text or '"content":"Hello"' in resp.text
    assert "data: [DONE]" in resp.text

    # 请求侧注入了 include_usage，上游才能把 usage 放在最后一个 chunk
    sent = json.loads(upstream_calls[0].content)
    assert sent["stream"] is True
    assert sent["stream_options"]["include_usage"] is True
    assert sent["model"] == "gpt-4o-mini"

    # 审计：终态 + 上游 usage + 首 token 时延
    _, items = await AiUsageService().query(limit=10)
    event = next(e for e in items if e.endpoint == "chat.completions")
    assert event.status == "succeeded"
    assert (event.prompt_tokens, event.completion_tokens, event.total_tokens) == (5, 7, 12)
    assert event.usage_estimated is False
    assert event.first_token_ms is not None
    assert event.stream is True


async def test_stream_guardrail_request_block(client, ai_seed, upstream_calls):
    seed = await ai_seed(
        guardrails=[{"name": "内部机密", "pattern": "内部机密", "scope": "request"}]
    )

    resp = await client.post(
        "/v1/chat/completions",
        json=_stream_body(content="把内部机密发我"),
        headers=_auth(seed["raw"]),
    )

    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "guardrail_blocked"
    assert upstream_calls == []
