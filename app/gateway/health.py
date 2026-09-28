import asyncio
import logging

from app.core.config import Settings
from app.gateway.runtime import RuntimeRegistry
from app.services.revision import RevisionStore
from app.services.service_manager import ServiceManager

logger = logging.getLogger(__name__)
SHUTDOWN_GRACE_SECONDS = 5.0

async def _sleep_until(stop: asyncio.Event, seconds: float) -> None:
    try:
        await asyncio.wait_for(stop.wait(), timeout=seconds)
    except TimeoutError:
        pass

class RevisionWatcher:
    def __init__(self, *, registry: RuntimeRegistry, revisions: RevisionStore, settings: Settings):
        self._registry = registry
        self._revisions = revisions
        self._settings = settings

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                await self._registry.snapshot()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("failed to refresh runtime snapshot")
            await _sleep_until(stop, self._settings.revision_poll_interval)

class HealthMonitor:
    def __init__(self, *, manager: ServiceManager, registry: RuntimeRegistry, revisions: RevisionStore, settings: Settings) -> None:
        self._manager = manager
        self._registry = registry
        self._revisions = revisions
        self._settings = settings

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                await self.check_all()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("health sweep failed")
            await _sleep_until(stop, self._settings.health_interval)

    async def check_all(self) -> None:
        from app.db.session import session_scope

        async with session_scope() as session:
            service_ids = await self._manager.list_enabled_service_ids(session)

        semaphore = asyncio.Semaphore(self._settings.health_max_concurrency)

        async def probe(service_id: int) -> None:
            async with semaphore:
                try:
                    await self._manager.check_health(service_id)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("health check raised for service %s", service_id)

        if service_ids:
            await asyncio.gather(*(probe(sid) for sid in service_ids))

        self._revisions.invalidate()
        self._registry.invalidate()

        # 顺手回收长时间全空闲的上游连接池：服务被删、或 URL/凭证改过之后，
        # 旧 key 对应的池不会再有请求进来，只能靠这里清理。
        try:
            await self._registry.pool.reap(
                max_idle_seconds=self._settings.upstream_pool_idle_ttl
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("上游连接池回收失败")

class BackgroundLoops:
    def __init__(self, *, registry: RuntimeRegistry, revisions: RevisionStore, manager: ServiceManager, settings: Settings) -> None:
        self._watcher = RevisionWatcher(registry=registry, revisions=revisions, settings=settings)
        self._health = HealthMonitor(manager=manager, registry=registry, revisions=revisions, settings=settings)
        self._stop: asyncio.Event | None = None
        self._tasks: list[asyncio.Task[None]] = []

    async def start(self) -> None:
        self._stop = asyncio.Event()
        self._tasks = [
            asyncio.create_task(
                self._watcher.run(self._stop), name="gateway-revision-watcher"
            ),
            asyncio.create_task(
                self._health.run(self._stop), name="gateway-health-monitor"
            ),
        ]

    async def stop(self) -> None:
        if self._stop is not None:
            self._stop.set()
        if not self._tasks:
            return
        done, pending = await asyncio.wait(
            self._tasks, timeout=SHUTDOWN_GRACE_SECONDS
        )
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            exception = task.exception()
            if exception is not None:
                logger.error("background task %s failed", task.get_name(), exc_info=exception)
        self._tasks.clear()