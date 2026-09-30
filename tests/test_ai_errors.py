"""错误格式测试：AiGatewayError 的七个构造函数，断言 OpenAI 兼容形状与 HTTP 码。

设计文档 §4.4。响应体必须是 {"error": {"message", "type", "code"}}，message 一律
中文；HTTP 码对齐：401/403×2/404/429×2/502。每条 code 各一条。
"""
import pytest

from app.ai.errors import AiGatewayError


def _has_cjk(text: str) -> bool:
    return any("一" <= ch <= "鿿" for ch in text)


def test_invalid_api_key_shape():
    e = AiGatewayError.invalid_api_key()
    assert e.http_status == 401
    assert e.code == "invalid_api_key"
    assert e.type == "authentication_error"
    assert _has_cjk(e.message)
    body = e.to_response()
    assert set(body["error"].keys()) == {"message", "type", "code"}
    assert body["error"]["code"] == "invalid_api_key"


def test_permission_denied_shape():
    e = AiGatewayError.permission_denied()
    assert e.http_status == 403
    assert e.code == "permission_denied"
    assert _has_cjk(e.message)
    assert e.to_response()["error"]["code"] == "permission_denied"


def test_guardrail_blocked_shape():
    e = AiGatewayError.guardrail_blocked()
    assert e.http_status == 403
    assert e.code == "guardrail_blocked"
    assert _has_cjk(e.message)
    assert e.to_response()["error"]["code"] == "guardrail_blocked"


def test_model_not_found_shape():
    e = AiGatewayError.model_not_found()
    assert e.http_status == 404
    assert e.code == "model_not_found"
    assert _has_cjk(e.message)
    assert e.to_response()["error"]["code"] == "model_not_found"


def test_insufficient_quota_shape():
    e = AiGatewayError.insufficient_quota()
    assert e.http_status == 429
    assert e.code == "insufficient_quota"
    assert _has_cjk(e.message)
    assert e.to_response()["error"]["code"] == "insufficient_quota"


def test_rate_limit_exceeded_shape():
    e = AiGatewayError.rate_limit_exceeded()
    assert e.http_status == 429
    assert e.code == "rate_limit_exceeded"
    assert _has_cjk(e.message)
    assert e.to_response()["error"]["code"] == "rate_limit_exceeded"


def test_upstream_error_shape():
    e = AiGatewayError.upstream_error()
    assert e.http_status == 502
    assert e.code == "upstream_error"
    assert _has_cjk(e.message)
    assert e.to_response()["error"]["code"] == "upstream_error"


def test_is_exception_with_attrs():
    e = AiGatewayError.model_not_found()
    assert isinstance(e, Exception)
    # 子类构造函数支持携带原始错误类型，便于审计 error_type 字段
    e2 = AiGatewayError.upstream_error(error_type="http_500")
    assert e2.error_type == "http_500"
    with pytest.raises(AiGatewayError):
        raise e
