from typing import Any

from fastmcp.tools import Tool, ToolResult
from mcp_types import ToolAnnotations
from pydantic import PrivateAttr

from app.gateway.runtime import RuntimeService
from app.services.policy import ToolDescriptor
from app.services.upstream import UpstreamClientPool, call_upstream_tool

#: 网关自定义元数据在 MCP `_meta` 里的键。`_meta` 是所有实现共用的扩展位，
#: fastmcp 自己会往里塞 `fastmcp` 键，用 `gateway/` 前缀把我们的约定圈出来，
#: 免得和上游、其他网关的扩展键撞车。
META_RISK = "gateway/risk"
META_REQUIRES_APPROVAL = "gateway/requiresApproval"

#: 风险等级到 MCP 标准注解的映射。只给 high 显式写：MCP 对 readOnlyHint 和
#: destructiveHint 的默认值本身就是悲观的（不假设只读、假设有破坏性），
#: 给 low/medium 写 false 等于替管理员断言"这个工具是只读的"——那是没有依据
#: 的断言，反而会让下游误判。精确等级始终在 `_meta` 里，不靠这两个布尔表达。
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
            # 把风险等级下发给下游：agent 要据此判断哪些调用该先找人确认。
            # 这里只负责给"已经能看到的工具"补标记，谁能看到什么仍由
            # PolicyMiddleware 按 token 授权过滤，可见性策略不变。
            #
            # requiresApproval 说的是工具的固有属性（这一类操作按网关定义就
            # 该人工确认），不是"当前 token 被拒了"——即便 token 开了
            # allow_high_risk、技术上调得动，下游仍应走 HITL。
            annotations=_RISK_ANNOTATIONS.get(descriptor.risk),
            meta={
                META_RISK: descriptor.risk,
                META_REQUIRES_APPROVAL: descriptor.risk == "high",
            },
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