"""GET /v1/models：只返回该 Key 授权且启用的模型，OpenAI 列表格式。"""
import pytest


def _auth(raw: str) -> dict:
    return {"Authorization": f"Bearer {raw}"}


async def test_models_lists_only_authorized(client, ai_seed):
    seed = await ai_seed(models=("chat", "embedding"))

    resp = await client.get("/v1/models", headers=_auth(seed["raw"]))

    assert resp.status_code == 200
    body = resp.json()
    assert body["object"] == "list"
    ids = sorted(item["id"] for item in body["data"])
    assert ids == ["gpt-4o-mini", "text-embedding-3-small"]
    for item in body["data"]:
        assert item["object"] == "model"
        assert item["owned_by"] == "oa"
        assert isinstance(item["created"], int)


async def test_models_requires_valid_key(client, ai_seed):
    await ai_seed()

    resp = await client.get("/v1/models")

    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "invalid_api_key"
