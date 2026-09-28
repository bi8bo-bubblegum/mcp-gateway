from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastapi import FastAPI, HTTPException
from fastmcp import FastMCP
from fastmcp.utilities.lifespan import combine_lifespans
from sqlalchemy import text

from app.admin import audit as audit_routes
from app.admin import services as service_routes
from app.admin import tokens as token_routes
from app.admin import tools as tool_routes
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.core.security import SecretBox, TokenHasher
from app.db.session import dispose_engine, init_engine, session_scope
from app.gateway.auth import GatewayTokenVerifier
from app.gateway.health import BackgroundLoops
from app.gateway.middleware import AuditMiddleware, PolicyMiddleware
from app.gateway.provider import GatewayProvider
from app.gateway.runtime import RuntimeRegistry
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


def build_container(
    settings: Settings | None = None,
    *,
    factory: UpstreamClientFactory | None = None,
) -> Container:
    """Build the process-wide container.

    `factory` is injectable so tests can substitute in-process FastMCP servers
    for real Streamable HTTP connections.
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
    )


def build_app(container: Container | None = None) -> FastAPI:
    container = container or build_container()

    # path="/" because the app is mounted at settings.mcp_path below, so the
    # externally visible endpoint is exactly /mcp.
    mcp_app = container.mcp.http_app(path="/", stateless_http=True)

    @asynccontextmanager
    async def gateway_lifespan(app: FastAPI):
        configure_logging()
        init_engine(container.settings.database_url, echo=container.settings.db_echo)
        async with session_scope() as session:
            await ensure_revision_row(session)
        app.state.container = container
        await container.background.start()
        try:
            yield
        finally:
            await container.background.stop()
            await dispose_engine()

    app = FastAPI(
        title="MCP Gateway",
        version="0.1.0",
        lifespan=combine_lifespans(gateway_lifespan, mcp_app.lifespan),
    )
    app.state.container = container

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