"""AI 网关错误格式：严格对齐 OpenAI 兼容错误体。

设计文档 §4.4。所有对外错误统一成 {"error": {"message", "type", "code"}}，HTTP 码
对齐：401/403×2/404/429×2/502。message 一律中文，便于客户端直接展示。
error_type 额外挂在异常上（不入响应体），供审计事件记录原始错误类别。
"""
from typing import Any


class AiGatewayError(Exception):
    """网关统一的对外错误。"""

    def __init__(
        self,
        message: str,
        *,
        type: str,
        code: str,
        http_status: int,
        error_type: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.type = type
        self.code = code
        self.http_status = http_status
        # 原始错误类别（如上游 HTTP 码、超时），仅用于审计，不进响应体
        self.error_type = error_type

    def to_response(self) -> dict[str, Any]:
        """OpenAI 兼容错误响应体。"""
        return {"error": {"message": self.message, "type": self.type, "code": self.code}}

    # ── 六个/七个构造函数 ────────────────────────────────────────
    # 每个构造函数都支持传入 error_type，作为审计 error_type 字段的来源。

    @classmethod
    def invalid_api_key(cls, *, error_type: str | None = None) -> "AiGatewayError":
        return cls(
            "API Key 无效、已撤销或已停用",
            type="authentication_error",
            code="invalid_api_key",
            http_status=401,
            error_type=error_type or "invalid_api_key",
        )

    @classmethod
    def permission_denied(cls, *, error_type: str | None = None) -> "AiGatewayError":
        return cls(
            "该 Key 未被授权访问此模型",
            type="permission_error",
            code="permission_denied",
            http_status=403,
            error_type=error_type or "permission_denied",
        )

    @classmethod
    def guardrail_blocked(cls, *, error_type: str | None = None) -> "AiGatewayError":
        return cls(
            "请求内容命中安全护栏，已被拦截",
            type="content_policy_violation",
            code="guardrail_blocked",
            http_status=403,
            error_type=error_type or "guardrail_blocked",
        )

    @classmethod
    def model_not_found(cls, *, error_type: str | None = None) -> "AiGatewayError":
        return cls(
            "模型不存在、未启用或所属厂商未启用",
            type="invalid_request_error",
            code="model_not_found",
            http_status=404,
            error_type=error_type or "model_not_found",
        )

    @classmethod
    def insufficient_quota(cls, *, error_type: str | None = None) -> "AiGatewayError":
        return cls(
            "当前周期内 token 配额已用尽",
            type="rate_limit_error",
            code="insufficient_quota",
            http_status=429,
            error_type=error_type or "insufficient_quota",
        )

    @classmethod
    def rate_limit_exceeded(cls, *, error_type: str | None = None) -> "AiGatewayError":
        return cls(
            "请求频率超过每分钟上限",
            type="rate_limit_error",
            code="rate_limit_exceeded",
            http_status=429,
            error_type=error_type or "rate_limit_exceeded",
        )

    @classmethod
    def upstream_error(
        cls, *, error_type: str | None = None, message: str | None = None
    ) -> "AiGatewayError":
        return cls(
            message or "上游服务异常或超时，请稍后重试",
            type="api_error",
            code="upstream_error",
            http_status=502,
            error_type=error_type or "upstream_error",
        )
