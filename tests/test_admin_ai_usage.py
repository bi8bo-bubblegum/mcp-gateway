"""用量审计 API：事件过滤分页 + 日汇总查询。"""
from datetime import date

from app.db.base import utcnow
from app.db.models import AiUsageDaily, AiUsageEvent


async def _seed_events(db, seed):
    async with db() as session:
        session.add_all(
            [
                AiUsageEvent(
                    request_id="r1",
                    key_id=seed["key_id"],
                    key_name="k",
                    model_id=seed["model_ids"]["gpt-4o-mini"],
                    model_alias="gpt-4o-mini",
                    provider_slug="oa",
                    endpoint="chat.completions",
                    stream=False,
                    status="succeeded",
                    total_tokens=12,
                    latency_ms=30,
                    started_at=utcnow(),
                ),
                AiUsageEvent(
                    request_id="r2",
                    key_id=seed["key_id"],
                    key_name="k",
                    model_alias="gpt-4o-mini",
                    endpoint="chat.completions",
                    stream=True,
                    status="denied",
                    denial_reason="insufficient_quota",
                    started_at=utcnow(),
                ),
            ]
        )
        await session.commit()


async def test_events_filter_by_status_and_paginate(client, admin_auth, ai_seed, db):
    seed = await ai_seed()
    await _seed_events(db, seed)

    all_page = (
        await client.get("/admin/v1/ai/usage/events", headers=admin_auth)
    ).json()
    assert all_page["total"] == 2
    assert all_page["limit"] == 50 and all_page["offset"] == 0

    denied = (
        await client.get("/admin/v1/ai/usage/events?status=denied", headers=admin_auth)
    ).json()
    assert denied["total"] == 1
    assert denied["items"][0]["denial_reason"] == "insufficient_quota"

    paged = (
        await client.get("/admin/v1/ai/usage/events?limit=1&offset=1", headers=admin_auth)
    ).json()
    assert paged["total"] == 2 and len(paged["items"]) == 1


async def test_events_filter_by_key_and_model(client, admin_auth, ai_seed, db):
    seed = await ai_seed()
    await _seed_events(db, seed)
    by_key = (
        await client.get(
            f"/admin/v1/ai/usage/events?key_id={seed['key_id']}", headers=admin_auth
        )
    ).json()
    assert by_key["total"] == 2
    by_model = (
        await client.get(
            f"/admin/v1/ai/usage/events?model_id={seed['model_ids']['gpt-4o-mini']}",
            headers=admin_auth,
        )
    ).json()
    assert by_model["total"] == 1


async def test_daily_summary_query(client, admin_auth, ai_seed, db):
    seed = await ai_seed()
    today = utcnow().date()
    async with db() as session:
        session.add(
            AiUsageDaily(
                key_id=seed["key_id"],
                day=today,
                requests=3,
                prompt_tokens=10,
                completion_tokens=20,
                total_tokens=30,
            )
        )
        await session.commit()

    rows = (
        await client.get(
            f"/admin/v1/ai/usage/daily?key_id={seed['key_id']}&from={today}&to={today}",
            headers=admin_auth,
        )
    ).json()
    assert len(rows) == 1
    assert rows[0]["day"] == date.isoformat(today)
    assert rows[0]["total_tokens"] == 30
