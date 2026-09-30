"""AI Key 管理 API：创建返回明文一次、策略更新、详情、撤销。"""
from app.core.security import generate_ai_key, token_display_prefix


async def test_create_returns_plaintext_once_only(client, admin_auth, ai_seed):
    seed = await ai_seed()
    resp = await client.post(
        "/admin/v1/ai/keys",
        json={
            "name": "ci-bot",
            "owner": "platform",
            "model_ids": list(seed["model_ids"].values()),
            "period": "day",
            "period_token_limit": 100000,
            "rate_limit_rpm": 60,
        },
        headers=admin_auth,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["key"].startswith("ai_")
    assert body["key_prefix"] == token_display_prefix(body["key"])
    assert "key_hash" not in body

    # 列表接口绝不带明文
    listed = (await client.get("/admin/v1/ai/keys", headers=admin_auth)).json()
    assert listed and all("key" not in item for item in listed)


async def test_create_without_models_is_allowed_but_deny_by_default(client, admin_auth):
    resp = await client.post(
        "/admin/v1/ai/keys",
        json={"name": "no-model"},
        headers=admin_auth,
    )
    assert resp.status_code == 201
    detail = (
        await client.get(f"/admin/v1/ai/keys/{resp.json()['id']}", headers=admin_auth)
    ).json()
    assert detail["model_ids"] == []


async def test_detail_returns_granted_models_and_quota(client, admin_auth, ai_seed):
    seed = await ai_seed()
    created = (
        await client.post(
            "/admin/v1/ai/keys",
            json={
                "name": "k",
                "model_ids": list(seed["model_ids"].values()),
                "period": "month",
                "period_token_limit": 500,
                "rate_limit_rpm": 5,
            },
            headers=admin_auth,
        )
    ).json()
    detail = (
        await client.get(f"/admin/v1/ai/keys/{created['id']}", headers=admin_auth)
    ).json()
    assert sorted(detail["model_ids"]) == sorted(seed["model_ids"].values())
    assert detail["period"] == "month"
    assert detail["period_token_limit"] == 500
    assert detail["rate_limit_rpm"] == 5


async def test_update_policy_replaces_model_grants(client, admin_auth, ai_seed):
    seed = await ai_seed(models=("chat", "embedding"))
    ids = list(seed["model_ids"].values())
    created = (
        await client.post(
            "/admin/v1/ai/keys",
            json={"name": "k", "model_ids": ids},
            headers=admin_auth,
        )
    ).json()

    updated = (
        await client.patch(
            f"/admin/v1/ai/keys/{created['id']}",
            json={"model_ids": [ids[0]], "rate_limit_rpm": 10},
            headers=admin_auth,
        )
    ).json()
    assert updated["rate_limit_rpm"] == 10
    detail = (
        await client.get(f"/admin/v1/ai/keys/{created['id']}", headers=admin_auth)
    ).json()
    assert detail["model_ids"] == [ids[0]]


async def test_revoke_marks_key_revoked(client, admin_auth, ai_seed):
    seed = await ai_seed()
    created = (
        await client.post(
            "/admin/v1/ai/keys",
            json={"name": "k", "model_ids": list(seed["model_ids"].values())},
            headers=admin_auth,
        )
    ).json()
    revoked = (
        await client.post(
            f"/admin/v1/ai/keys/{created['id']}/revoke", headers=admin_auth
        )
    ).json()
    assert revoked["revoked_at"] is not None
    assert revoked["enabled"] is False


async def test_unknown_key_returns_404(client, admin_auth):
    assert (await client.get("/admin/v1/ai/keys/999", headers=admin_auth)).status_code == 404


def test_generated_key_prefix_is_stable():
    # 前缀约定必须与客户端接入文档一致（ai_ + 前 12 位展示）
    raw = generate_ai_key()
    assert raw.startswith("ai_") and token_display_prefix(raw).startswith("ai_")
