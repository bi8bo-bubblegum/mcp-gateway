from typing import Any

from cryptography.x509 import name
from fastmcp.tools import Tool, ToolResult
from pydantic import PrivateAttr

from app.gateway.runtime import RuntimeService
from app.services.policy import ToolDescriptor
from app.services.upstream import UpstreamClientFactory, call_upstream_tool

class GatewayTool(Tool):
    _descriptor: ToolDescriptor = PrivateAttr()
    _service: RuntimeService = PrivateAttr()
    _factory: UpstreamClientFactory = PrivateAttr()
    _timeout: float = PrivateAttr()

    def __init__(self, *, descriptor: ToolDescriptor, service: RuntimeService, factory: UpstreamClientFactory, timeout: float) -> None:
        super().__init__(
            name=descriptor.effective_name,
            description=descriptor.description,
            parameters=descriptor.input_schema,
        )
        self._descriptor = descriptor
        self._service = service
        self._factory = factory
        self._timeout = timeout

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        return await call_upstream_tool(
            self._factory,
            url=self._service.url,
            auth=self._service.auth,
            upstream_name=self._descriptor.upstream_name,
            arguments=arguments,
            timeout=self._timeout,
        )