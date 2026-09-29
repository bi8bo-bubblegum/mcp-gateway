from typing import Any

from fastmcp.tools import Tool, ToolResult
from mcp_types import ToolAnnotations
from pydantic import PrivateAttr

from app.gateway.runtime import RuntimeService
from app.services.policy import ToolDescriptor
from app.services.upstream import UpstreamClientPool, call_upstream_tool

#: 风险等级到 MCP 标准注解的映射。只给 high 显式写：MCP 对 readOnlyHint 和
#: destructiveHint 的默认值本身就是悲观的（不假设只读、假设有破坏性），
#: 给 low/medium 写 false 等于替管理员断言"这个工具是只读的"——那是没有依据
#: 的断言，反而会让下游误判。
#:
#: 这里只给通用客户端一个"是不是高风险"的粗粒度信号——Claude 这类客户端
#: 不会去查网关的库。精确等级（low/medium/high）不走协议透传，由下游按
#: 工具名查 tools 表获取：那里是 risk 的源头，也拿得到管理员改动后的最新值，
#: 不受 tools/list 快照时效的限制。
_RISK_ANNOTATIONS = {
    "high": ToolAnnotations(read_only_hint=False, destructive_hint=True),
}

class GatewayTool(Tool):
    _descriptor: ToolDescriptor = PrivateAttr()
    _service: RuntimeService = PrivateAttr()
    _pool: UpstreamClientPool = PrivateAttr()
    _timeout: float = PrivateAttr()

    def __init__(self, *, descriptor: ToolDescriptor, service: RuntimeService, pool: UpstreamClientPool, timeout: float) -> None:
        super().__init__(
            name=descriptor.effective_name,
            description=descriptor.description,
            parameters=descriptor.input_schema,
            # 把高风险标记下发给下游：通用客户端据此走确认流程。这里只负责
            # 给"已经能看到的工具"补标记，谁能看到什么仍由 PolicyMiddleware
            # 按 token 授权过滤，可见性策略不变。
            annotations=_RISK_ANNOTATIONS.get(descriptor.risk),
        )
        self._descriptor = descriptor
        self._service = service
        self._pool = pool
        self._timeout = timeout

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        return await call_upstream_tool(
            self._pool,
            url=self._service.url,
            auth=self._service.auth,
            upstream_name=self._descriptor.upstream_name,
            arguments=arguments,
            timeout=self._timeout,
        )