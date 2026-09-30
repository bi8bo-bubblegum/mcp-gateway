"""装配回归：数据面 + 五个管理路由都必须在 app 的 OpenAPI schema 里（M2-M4 出口条件）。

用 `app.openapi()["paths"]` 而不是 `app.routes`：前者是 Swagger 展示的对外契约，
也是这个版本 FastAPI 唯一稳定可见的"已注册路径"视图。
"""
from app.main import build_app, build_container


def _paths(settings) -> set[str]:
    return set(build_app(build_container(settings)).openapi()["paths"])


def test_data_plane_routes_registered(settings):
    paths = _paths(settings)
    assert "/v1/chat/completions" in paths
    assert "/v1/embeddings" in paths
    assert "/v1/models" in paths


def test_admin_routes_registered(settings):
    paths = _paths(settings)
    assert "/admin/v1/ai/providers" in paths
    assert "/admin/v1/ai/models" in paths
    assert "/admin/v1/ai/models/pull" in paths
    assert "/admin/v1/ai/keys" in paths
    assert "/admin/v1/ai/usage/events" in paths
    assert "/admin/v1/ai/guardrails" in paths


def test_existing_mcp_routes_untouched(settings):
    paths = _paths(settings)
    assert "/admin/v1/services" in paths
    assert "/admin/v1/tokens" in paths
    assert "/admin/v1/tools" in paths
    assert "/admin/v1/audit-events" in paths
    assert "/health/live" in paths
    assert "/health/ready" in paths


async def test_swagger_and_ai_endpoints_answer(client):
    # Swagger 本身可访问（文档站是交付物的一部分）
    assert (await client.get("/docs")).status_code == 200
    # 数据面与管理端都在同一进程里真实可路由
    assert (await client.get("/v1/models")).status_code == 401
    assert (await client.get("/admin/v1/ai/providers")).status_code == 401
