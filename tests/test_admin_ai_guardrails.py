"""护栏规则管理 API：CRUD + 批量导入。"""
from sqlalchemy import select

from app.db.models import GuardrailRule


async def test_create_and_list_rule(client, admin_auth, db):
    resp = await client.post(
        "/admin/v1/ai/guardrails",
        json={"name": "内部代号", "pattern": "Project Falcon", "scope": "both"},
        headers=admin_auth,
    )
    assert resp.status_code == 201
    assert resp.json()["scope"] == "both"

    rows = (await client.get("/admin/v1/ai/guardrails", headers=admin_auth)).json()
    assert [r["name"] for r in rows] == ["内部代号"]


async def test_bulk_import_skips_blank_and_duplicates(client, admin_auth, db):
    # 预置一条已存在的关键词，导入时应被跳过
    async with db() as session:
        session.add(
            GuardrailRule(name="旧", pattern="PASSWORD", scope="request", action="block")
        )
        await session.commit()

    resp = await client.post(
        "/admin/v1/ai/guardrails/bulk",
        json={
            "text": "  PASSWORD  \n\n内部项目\n内部项目\n  \nSECRET_KEY\n",
            "scope": "request",
        },
        headers=admin_auth,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["created"] == 2  # 内部项目 / SECRET_KEY
    assert body["skipped"] == 2  # PASSWORD 已存在 + 文本内重复

    async with db() as session:
        patterns = set(
            (await session.execute(select(GuardrailRule.pattern))).scalars()
        )
    assert patterns == {"PASSWORD", "内部项目", "SECRET_KEY"}


async def test_toggle_and_delete_rule(client, admin_auth, db):
    created = (
        await client.post(
            "/admin/v1/ai/guardrails",
            json={"name": "n", "pattern": "kw"},
            headers=admin_auth,
        )
    ).json()
    disabled = (
        await client.patch(
            f"/admin/v1/ai/guardrails/{created['id']}",
            json={"enabled": False},
            headers=admin_auth,
        )
    ).json()
    assert disabled["enabled"] is False

    assert (
        await client.delete(
            f"/admin/v1/ai/guardrails/{created['id']}", headers=admin_auth
        )
    ).status_code == 204
    assert (await client.get("/admin/v1/ai/guardrails", headers=admin_auth)).json() == []


async def test_rule_affects_data_plane_immediately(client, admin_auth, ai_seed, upstream_calls):
    """管理端新增规则后，数据面下一个请求就该被拦（无需重启/等缓存）。"""
    seed = await ai_seed()
    await client.post(
        "/admin/v1/ai/guardrails",
        json={"name": "blk", "pattern": "forbidden", "scope": "request"},
        headers=admin_auth,
    )
    resp = await client.post(
        "/v1/chat/completions",
        json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "forbidden thing"}]},
        headers={"Authorization": f"Bearer {seed['raw']}"},
    )
    assert resp.status_code == 403
    assert upstream_calls == []  # 命中护栏绝不透传上游
