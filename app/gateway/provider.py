from collections.abc import Sequence

from fastmcp.server.providers import Provider
from fastmcp.tools import Tool

from app.gateway.runtime import RuntimeRegistry, RuntimeSnapshot
from app.gateway.tools import GatewayTool
from app.services.policy import ToolDescriptor

class GatewayProvider(Provider):
    def __init__(self, registry: RuntimeRegistry) -> None:
        super().__init__()
        self._registry = registry

    async def _list_tools(self) -> Sequence[Tool]:
        snapshot = await self._registry.snapshot()
        return [self._build(snapshot, item) for item in snapshot.all_descriptors()]

    async def _get_tools(self, name: str, version=None) -> Tool | None:
        snapshot = await self._registry.snapshot()
        descriptor = snapshot.descriptor(name)
        if descriptor is None:
            return None
        return self._build(snapshot, descriptor)

    def _build(self, snapshot: RuntimeSnapshot, descriptor: ToolDescriptor) -> Tool:
        service = snapshot.services[descriptor.service_id]
        return GatewayTool(
            descriptor=descriptor,
            service=service,
            factory=self._registry.factory,
            timeout=self._registry.upstream_timeout,
        )