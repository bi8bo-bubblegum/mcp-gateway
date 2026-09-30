"""embeddings 端到端：kind 校验、usage 记账（上游只给 prompt/total）。"""
from sqlalchemy import select

from app.db.models import AiUsageDaily
from app.services.ai_usage_service import AiUsageService


def _auth(raw: str) -> dict:
    return {"Authorization": f"Bearer {raw}"}


async def test_embeddings_success(client, db, ai_seed, upstream_calls):
    seed = await ai_seed(models=("chat", "embedding"))

    resp = await client.post(
        "/v1/embeddings",
        json={"model": "text-embedding-3-small", "input": "你好"},
        headers=_auth(seed["raw"]),
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["data"][0]["embedding"] == [0.1, 0.2, 0.3]

    # 上游收到的是注册里的上游模型名
    import json

    sent = json.loads(upstream_calls[0].content)
    assert sent["model"] == "text-embedding-3-small"

    # usage：上游只回 prompt/total（无 completion），网关应记 completion=0
    _, items = await AiUsageService().query(limit=10)
    event = next(e for e in items if e.endpoint == "embeddings")
    assert event.status == "succeeded"
    assert (event.prompt_tokens, event.completion_tokens, event.total_tokens) == (3, 0, 3)

    async with db() as session:
        daily = (
            await session.execute(
                select(AiUsageDaily).where(AiUsageDaily.key_id == seed["key_id"])
            )
        ).scalar_one()
    assert daily.requests == 1
    assert daily.total_tokens == 3


async def test_chat_model_rejected_on_embeddings(client, ai_seed, upstream_calls):
    seed = await ai_seed(models=("chat",))  # 只有 chat 模型

    resp = await client.post(
        "/v1/embeddings",
        json={"model": "gpt-4o-mini", "input": "你好"},
        headers=_auth(seed["raw"]),
    )

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "model_not_found"
    assert upstream_calls == []
