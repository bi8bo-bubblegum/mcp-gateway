"""厂商管理 API：CRUD + 上游密钥加密 + 健康检查。"""
from app.core.security import SecretBox
from app.db.models import AiProvider


async def test_requires_admin_auth(client):
    # 无凭据 → 401，管理端接口不能裸奔
    assert (await client.get("/admin/v1/ai/providers")).status_code == 401


async def test_create_encrypts_key_and_never_returns_it(client, admin_auth, db, settings):
    resp = await client.post(
        "/admin/v1/ai/providers",
        json={
            "slug": "oa",
            "name": "OpenAI",
            "base_url": "http://fake/v1",
            "api_key": "sk-top-secret",
            "enabled": True,
        },
        headers=admin_auth,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["slug"] == "oa" and body["enabled"] is True
    # 响应绝不能回显上游密钥（明文或密文都不行）
    assert "sk-top-secret" not in resp.text
    assert "api_key" not in body and "api_key_ciphertext" not in body

    # 库里是密文，且用同一 secret_key 能解回原值
    async with db() as session:
        row = await session.get(AiProvider, body["id"])
    assert row.api_key_ciphertext and "sk-top-secret" not in row.api_key_ciphertext
    assert SecretBox(settings.secret_key).decrypt(row.api_key_ciphertext)["bearer_token"] == "sk-top-secret"


async def test_duplicate_slug_rejected(client, admin_auth, ai_seed):
    seed = await ai_seed()  # 已有一个 slug=oa
    assert seed["provider_id"] > 0
    resp = await client.post(
        "/admin/v1/ai/providers",
        json={"slug": "oa", "name": "重复", "base_url": "http://fake/v1"},
        headers=admin_auth,
    )
    assert resp.status_code == 400


async def test_health_check_healthy(client, admin_auth, ai_seed, upstream):
    seed = await ai_seed()
    resp = await client.post(
        f"/admin/v1/ai/providers/{seed['provider_id']}/health", headers=admin_auth
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["health"] == "healthy"
    assert body["consecutive_failures"] == 0
    assert body["last_checked_at"] is not None


async def test_health_check_unhealthy_counts_failures(client, admin_auth, ai_seed, upstream):
    seed = await ai_seed()
    upstream.state.mode = "http_500"
    body = (
        await client.post(
            f"/admin/v1/ai/providers/{seed['provider_id']}/health", headers=admin_auth
        )
    ).json()
    assert body["health"] == "unhealthy"
    assert body["consecutive_failures"] == 1
    assert body["last_error"]


async def test_enable_disable_and_delete(client, admin_auth, ai_seed, db):
    seed = await ai_seed()
    pid = seed["provider_id"]

    assert (
        await client.post(f"/admin/v1/ai/providers/{pid}/disable", headers=admin_auth)
    ).json()["enabled"] is False
    assert (
        await client.post(f"/admin/v1/ai/providers/{pid}/enable", headers=admin_auth)
    ).json()["enabled"] is True

    assert (
        await client.delete(f"/admin/v1/ai/providers/{pid}", headers=admin_auth)
    ).status_code == 204
    assert (
        await client.get(f"/admin/v1/ai/providers/{pid}", headers=admin_auth)
    ).status_code == 404


async def test_update_base_url_and_name(client, admin_auth, ai_seed):
    seed = await ai_seed()
    body = (
        await client.patch(
            f"/admin/v1/ai/providers/{seed['provider_id']}",
            json={"name": "OpenAI 官方", "base_url": "http://fake/v1"},
            headers=admin_auth,
        )
    ).json()
    assert body["name"] == "OpenAI 官方"
