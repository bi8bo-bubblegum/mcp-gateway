"""模型管理 API：手动 CRUD + 从上游拉取 + 批量导入。"""
from sqlalchemy import select

from app.db.models import AiModel


async def test_list_filtered_by_provider_and_kind(client, admin_auth, ai_seed):
    seed = await ai_seed(models=("chat", "embedding"))
    all_rows = (await client.get("/admin/v1/ai/models", headers=admin_auth)).json()
    assert len(all_rows) == 2

    chat_only = (
        await client.get(
            f"/admin/v1/ai/models?provider_id={seed['provider_id']}&kind=chat",
            headers=admin_auth,
        )
    ).json()
    assert [m["alias"] for m in chat_only] == ["gpt-4o-mini"]


async def test_create_model_and_duplicate_alias(client, admin_auth, ai_seed):
    seed = await ai_seed()
    ok = await client.post(
        "/admin/v1/ai/models",
        json={
            "provider_id": seed["provider_id"],
            "provider_model_name": "gpt-4o",
            "alias": "gpt-4o",
            "kind": "chat",
        },
        headers=admin_auth,
    )
    assert ok.status_code == 201

    dup = await client.post(
        "/admin/v1/ai/models",
        json={
            "provider_id": seed["provider_id"],
            "provider_model_name": "gpt-4o-other",
            "alias": "gpt-4o",
            "kind": "chat",
        },
        headers=admin_auth,
    )
    assert dup.status_code == 400


async def test_create_rejects_unknown_kind(client, admin_auth, ai_seed):
    seed = await ai_seed()
    resp = await client.post(
        "/admin/v1/ai/models",
        json={
            "provider_id": seed["provider_id"],
            "provider_model_name": "x",
            "alias": "x",
            "kind": "vision",
        },
        headers=admin_auth,
    )
    assert resp.status_code == 422


async def test_pull_models_from_upstream(client, admin_auth, ai_seed, upstream):
    seed = await ai_seed()
    resp = await client.get(
        f"/admin/v1/ai/models/pull?provider_id={seed['provider_id']}", headers=admin_auth
    )
    assert resp.status_code == 200
    pulled = resp.json()
    assert [m["id"] for m in pulled] == ["gpt-4o-mini", "text-embedding-3-small"]
    assert pulled[0]["owned_by"] == "openai"


async def test_import_models_skips_existing(client, admin_auth, ai_seed, db):
    seed = await ai_seed()  # gpt-4o-mini 已存在
    resp = await client.post(
        "/admin/v1/ai/models/import",
        json={
            "provider_id": seed["provider_id"],
            "items": [
                {"provider_model_name": "gpt-4o-mini", "kind": "chat"},
                {"provider_model_name": "text-embedding-3-small", "kind": "embedding"},
            ],
        },
        headers=admin_auth,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["created"] == 1
    assert body["skipped"] == 1

    async with db() as session:
        aliases = set(
            (await session.execute(select(AiModel.alias))).scalars()
        )
    assert aliases == {"gpt-4o-mini", "text-embedding-3-small"}
