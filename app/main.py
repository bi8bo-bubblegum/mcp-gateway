from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastmcp import FastMCP
from fastmcp.utilities.lifespan import combine_lifespans
from sqlalchemy import text

from app.admin import audit as audit_routes
from app.admin import services as service_routes
from app.admin import tokens as token_routes
from app.admin import tools as tool_routes
from app.ai.errors import AiGatewayError
from app.ai.guardrail import GuardrailLoader
from app.ai.quota import RateLimiter
from app.ai.router import router as ai_router
from app.ai.snapshot import AiRuntimeRegistry
from app.ai.upstream import AiUpstreamPool, ClientFactory
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.core.security import SecretBox, TokenHasher
from app.db.session import dispose_engine, init_engine, session_scope
from app.gateway.auth import GatewayTokenVerifier
from app.gateway.health import BackgroundLoops
from app.gateway.middleware import AuditMiddleware, PolicyMiddleware
from app.gateway.provider import GatewayProvider
from app.gateway.runtime import RuntimeRegistry
from app.services.ai_key_service import AiKeyService
from app.services.ai_usage_service import AiUsageService
from app.services.audit import AuditService
from app.services.revision import RevisionStore, ensure_revision_row
from app.services.service_manager import ServiceManager
from app.services.token_service import TokenService
from app.services.upstream import (
    StreamableHttpClientFactory,
    UpstreamClientFactory,
)


@dataclass
class Container:
    """Process-wide wiring. Constructed once; holds caches, never sessions."""

    settings: Settings
    hasher: TokenHasher
    secret_box: SecretBox
    revisions: RevisionStore
    registry: RuntimeRegistry
    service_manager: ServiceManager
    token_service: TokenService
    audit_service: AuditService
    background: BackgroundLoops
    mcp: FastMCP
    # ── AI 网关数据面（§4.1 九步链路用到的服务）──
    ai_keys: AiKeyService
    ai_registry: AiRuntimeRegistry
    ai_usage: AiUsageService
    ai_guardrails: GuardrailLoader
    ai_pool: AiUpstreamPool
    ai_rate_limiter: RateLimiter


def build_container(
    settings: Settings | None = None,
    *,
    factory: UpstreamClientFactory | None = None,
    ai_client_factory: ClientFactory | None = None,
) -> Container:
    """Build the process-wide container.

    `factory` is injectable so tests can substitute in-process FastMCP servers
    for real Streamable HTTP connections. `ai_client_factory` 同理，让 AI 网关
    的上游 HTTP 客户端可注入（测试里替换为 httpx.ASGITransport(app=假上游)）。
    """
    settings = settings or get_settings()
    hasher = TokenHasher(settings.secret_key)
    secret_box = SecretBox(settings.secret_key)
    upstream_factory = factory or StreamableHttpClientFactory()

    revisions = RevisionStore(settings.revision_cache_ttl)
    registry = RuntimeRegistry(
        settings=settings,
        revisions=revisions,
        secret_box=secret_box,
        factory=upstream_factory,
    )
    service_manager = ServiceManager(
        settings=settings,
        factory=upstream_factory,
        secret_box=secret_box,
        hasher=hasher,
    )
    token_service = TokenService(
        settings=settings, hasher=hasher, revisions=revisions
    )
    audit_service = AuditService(hasher=hasher)

    # ── AI 网关服务 ──
    ai_keys = AiKeyService(settings=settings, hasher=hasher, revisions=revisions)
    ai_registry = AiRuntimeRegistry(
        settings=settings, revisions=revisions, secret_box=secret_box
    )
    ai_usage = AiUsageService()
    ai_guardrails = GuardrailLoader()
    ai_pool = AiUpstreamPool(settings, client_factory=ai_client_factory)
    ai_rate_limiter = RateLimiter(settings)

    mcp = FastMCP(
        "MCP Gateway",
        instructions=(
            "Unified MCP gateway. The tool catalog is scoped to the token used "
            "to connect; call tools by their listed names."
        ),
        auth=GatewayTokenVerifier(token_service),
        providers=[GatewayProvider(registry)],
        # Order matters: audit is outermost, so it also sees policy denials.
        middleware=[
            AuditMiddleware(tokens=token_service, audit=audit_service),
            PolicyMiddleware(tokens=token_service, registry=registry),
        ],
    )

    background = BackgroundLoops(
        registry=registry,
        revisions=revisions,
        manager=service_manager,
        settings=settings,
    )

    return Container(
        settings=settings,
        hasher=hasher,
        secret_box=secret_box,
        revisions=revisions,
        registry=registry,
        service_manager=service_manager,
        token_service=token_service,
        audit_service=audit_service,
        background=background,
        mcp=mcp,
        ai_keys=ai_keys,
        ai_registry=ai_registry,
        ai_usage=ai_usage,
        ai_guardrails=ai_guardrails,
        ai_pool=ai_pool,
        ai_rate_limiter=ai_rate_limiter,
    )


def build_app(container: Container | None = None) -> FastAPI:
    container = container or build_container()

    # path="/" because the app is mounted at settings.mcp_path below, so the
    # externally visible endpoint is exactly /mcp.
    mcp_app = container.mcp.http_app(path="/", stateless_http=True)

    @asynccontextmanager
    async def gateway_lifespan(app: FastAPI):
        configure_logging()
        init_engine(
            container.settings.database_url,
            echo=container.settings.db_echo,
            pool_size=container.settings.db_pool_size,
            max_overflow=container.settings.db_max_overflow,
            pool_timeout=container.settings.db_pool_timeout,
            pool_recycle=container.settings.db_pool_recycle,
        )
        async with session_scope() as session:
            await ensure_revision_row(session)
        app.state.container = container
        await container.background.start()
        try:
            yield
        finally:
            await container.background.stop()
            # 关闭所有上游长连接，否则优雅退出会挂在这里等它们超时
            await container.registry.pool.aclose()
            # AI 网关上游连接池同样要在关停时释放，避免退出挂起
            await container.ai_pool.aclose()
            await dispose_engine()

    app = FastAPI(
        title="MCP Gateway",
        version="0.1.0",
        lifespan=combine_lifespans(gateway_lifespan, mcp_app.lifespan),
    )
    app.state.container = container

    # AI 网关错误统一转成 OpenAI 兼容错误体（§4.4）
    @app.exception_handler(AiGatewayError)
    async def ai_gateway_error_handler(request: Request, exc: AiGatewayError) -> JSONResponse:
        return JSONResponse(status_code=exc.http_status, content=exc.to_response())

    app.include_router(ai_router)
    app.include_router(service_routes.router)
    app.include_router(tool_routes.router)
    app.include_router(token_routes.router)
    app.include_router(audit_routes.router)

    @app.get("/health/live", tags=["health"])
    async def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready", tags=["health"])
    async def ready() -> dict[str, str]:
        try:
            async with session_scope() as session:
                await session.execute(text("SELECT 1"))
        except Exception as error:  # noqa: BLE001 - readiness is a health signal
            raise HTTPException(
                status_code=503, detail="database unavailable"
            ) from error
        return {"status": "ready"}

    app.mount(container.settings.mcp_path, mcp_app)
    return app


app = build_app()


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
    )