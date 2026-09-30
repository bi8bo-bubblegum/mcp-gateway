"""非流式 chat/completions 端到端：设计文档 §4.1 九步链路 + §4.4 错误码。

全程走内存假上游（conftest 的 client fixture 已把 AiUpstreamPool 的工厂换成
ASGITransport(app=假上游)），不触网；并断言"护栏拦截时上游未被调用"。
"""
import json

from sqlalchemy import select

from app.db.base import utcnow
from app.db.models import AiModel, AiUsageDaily
from app.services.ai_usage_service import AiUsageService


def _chat_body(model: str = "gpt-4o-mini", content: str = "你好", stream: bool = False) -> dict:
    return {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "stream": stream,
    }


def _auth(raw: str) -> dict:
    return {"Authorization": f"Bearer {raw}"}


async def _events(**kwargs):
    total, items = await AiUsageService().query(limit=50, **kwargs)
    return total, list(items)


async def test_non_stream_success_records_usage(client, db, ai_seed, upstream_calls):
    seed = await ai_seed()

    resp = await client.post(
        "/v1/chat/completions", json=_chat_body(), headers=_auth(seed["raw"])
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["choices"][0]["message"]["content"] == "Hello"
    assert body["usage"]["total_tokens"] == 12

    # 上游收到的是 provider_model_name（不是对外 alias）
    sent = json.loads(upstream_calls[0].content)
    assert sent["model"] == "gpt-4o-mini"

    # 审计：终态 + 与上游一致的 token 数 + 时延
    _, items = await _events()
    event = next(e for e in items if e.endpoint == "chat.completions")
    assert event.status == "succeeded"
    assert (event.prompt_tokens, event.completion_tokens, event.total_tokens) == (5, 7, 12)
    assert event.usage_estimated is False
    assert event.latency_ms is not None
    assert event.key_id == seed["key_id"]

    # 日汇总 +1
    async with db() as session:
        daily = (
            await session.execute(
                select(AiUsageDaily).where(AiUsageDaily.key_id == seed["key_id"])
            )
        ).scalar_one()
    assert daily.requests == 1
    assert daily.total_tokens == 12


async def test_missing_key_401(client, ai_seed):
    await ai_seed()

    resp = await client.post("/v1/chat/completions", json=_chat_body())

    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "invalid_api_key"
    # 鉴权失败发生在审计之前，不应留下事件
    total, _ = await _events()
    assert total == 0


async def test_unauthorized_model_403(client, db, ai_seed, upstream_calls):
    seed = await ai_seed()
    # 再建一个已启用但未授权给该 Key 的模型：解析得到、授权不通过 → 403
    async with db() as session:
        session.add(
            AiModel(
                provider_id=seed["provider_id"],
                provider_model_name="gpt-4o",
                alias="not-allowed",
                kind="chat",
                enabled=True,
            )
        )
        await session.commit()

    resp = await client.post(
        "/v1/chat/completions",
        json=_chat_body(model="not-allowed"),
        headers=_auth(seed["raw"]),
    )

    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "permission_denied"
    assert upstream_calls == []


async def test_unknown_model_404(client, ai_seed, upstream_calls):
    seed = await ai_seed()

    resp = await client.post(
        "/v1/chat/completions", json=_chat_body(model="nope"), headers=_auth(seed["raw"])
    )

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "model_not_found"
    assert upstream_calls == []


async def test_quota_exceeded_429(client, db, ai_seed, upstream_calls):
    seed = await ai_seed(period="day", quota=1)
    # 先占满当日配额：等于限额即拒
    async with db() as session:
        session.add(
            AiUsageDaily(
                key_id=seed["key_id"],
                day=utcnow().date(),
                requests=1,
                prompt_tokens=1,
                completion_tokens=0,
                total_tokens=1,
            )
        )
        await session.commit()

    resp = await client.post(
        "/v1/chat/completions", json=_chat_body(), headers=_auth(seed["raw"])
    )

    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == "insufficient_quota"
    assert upstream_calls == []
    _, items = await _events()
    assert items[0].status == "denied"
    assert items[0].denial_reason == "insufficient_quota"


async def test_guardrail_blocks_request_and_skips_upstream(client, ai_seed, upstream_calls):
    seed = await ai_seed(
        guardrails=[{"name": "内部机密", "pattern": "内部机密", "scope": "request"}]
    )

    resp = await client.post(
        "/v1/chat/completions",
        json=_chat_body(content="帮我查一下内部机密的定价"),
        headers=_auth(seed["raw"]),
    )

    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "guardrail_blocked"
    # 关键：护栏命中必须在转发前拦下
    assert upstream_calls == []
    _, items = await _events()
    assert items[0].status == "denied"
    assert items[0].denial_reason == "guardrail_blocked"
    # 只记规则引用，不存命中原文
    assert items[0].guardrail_hits
    assert "pattern" not in json.dumps(items[0].guardrail_hits)


async def test_upstream_500_maps_to_502(client, ai_seed, upstream):
    seed = await ai_seed()
    upstream.state.mode = "http_500"

    resp = await client.post(
        "/v1/chat/completions", json=_chat_body(), headers=_auth(seed["raw"])
    )

    assert resp.status_code == 502
    assert resp.json()["error"]["code"] == "upstream_error"
    _, items = await _events()
    assert items[0].status == "failed"
    assert items[0].error_type
