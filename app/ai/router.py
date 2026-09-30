"""AI 网关数据面路由：/v1/chat/completions（流式+非流式）、/v1/embeddings、/v1/models。

链路严格按设计文档 §4.1 九步走：鉴权 → 模型解析 → 授权 → 配额 → 限流 →
请求侧护栏 → 审计 start（fail-closed，且必须在转发之前）→ 转发 → 响应+记账。
护栏策略（§4.3）：请求侧命中一律 block 且不透传上游；非流式响应侧命中也 block，
流式响应侧只检测入审计、不中断流。

所有对外错误统一成 AiGatewayError，由 main.py 注册的异常处理器转成 OpenAI 兼容体。
审计 guardrail_hits 只存规则引用（rule_id/rule_name），不存命中原文（延续"审计不存原文"哲学）。
"""
import calendar
import logging
import time
import uuid
from typing import Any

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import Response, StreamingResponse

from app.ai.errors import AiGatewayError
from app.ai.guardrail import GuardrailEngine, GuardrailHit, GuardrailLoader
from app.ai.metering import Usage, estimate_usage, parse_usage, record_daily
from app.ai.quota import QuotaChecker, RateLimiter
from app.ai.snapshot import AiRuntimeRegistry
from app.ai.streaming import _empty_usage, prepare_stream_body, relay_stream
from app.ai.upstream import AiUpstreamPool
from app.db.models import AI_MODEL_KIND_EMBEDDING
from app.db.session import session_scope
from app.services.ai_key_service import AiKeyService, AiKeySnapshot
from app.services.ai_usage_service import AiAuditWriteError, AiUsageService

logger = logging.getLogger(__name__)

# 注意：上游 path 不带 /v1 前缀——厂商 base_url 自身已含 /v1（OpenAI 约定
# base_url=https://api.openai.com/v1，SDK 再请求 /chat/completions）。若这里写成
# /v1/chat/completions，拼出来会变成 /v1/v1/... 而 404。
CHAT_PATH = "/chat/completions"
EMBEDDINGS_PATH = "/embeddings"
# /v1/models 的 created 字段：模型注册时间（naive UTC → epoch）；兜底值保持与假上游一致
_MODELS_CREATED_FALLBACK = 1700000000

router = APIRouter(prefix="/v1")


# ── 内部小工具 ──────────────────────────────────────────────────────

def _extract_raw_key(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    parts = auth.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip()


def _request_id(request: Request) -> str:
    return request.headers.get("x-request-id") or uuid.uuid4().hex


def _hit_dict(hit: GuardrailHit) -> dict[str, Any]:
    # 只暴露规则引用，绝不带回命中原文
    return {"rule_id": hit.rule_id, "rule_name": hit.rule_name}


def _request_guardrail_text(body: dict[str, Any], endpoint: str) -> str:
    """从请求体提取用于请求侧护栏扫描的文本。"""
    if endpoint == "embeddings":
        inp = body.get("input", "")
        if isinstance(inp, list):
            return " ".join(str(x) for x in inp)
        return str(inp)
    parts: list[str] = []
    for msg in body.get("messages", []) or []:
        content = msg.get("content")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for piece in content:
                if isinstance(piece, dict) and piece.get("type") == "text":
                    parts.append(piece.get("text", ""))
    return "\n".join(parts)


def _response_text(data: dict[str, Any]) -> str:
    parts: list[str] = []
    for choice in data.get("choices", []) or []:
        msg = choice.get("message") or {}
        c = msg.get("content")
        if isinstance(c, str):
            parts.append(c)
    return "\n".join(parts)


def _httpx_error_type(exc: Exception) -> str:
    if isinstance(exc, httpx.TimeoutException):
        return "upstream_timeout"
    return "upstream_http_error"


async def _start_audit(
    ai_usage: AiUsageService,
    *,
    endpoint: str,
    stream: bool,
    request_id: str,
    key_id: int | None = None,
    key_name: str | None = None,
    model_id: int | None = None,
    model_alias: str | None = None,
    provider_slug: str | None = None,
) -> int:
    """写审计起始事件（fail-closed）。

    写不进去说明 DB 不可用或审计链路断了——按设计 §4.1⑦，这种状态下网关不能发出
    它无法记录的调用，故转成 upstream_error 拒绝转发（宁可误拒，不可漏审）。
    """
    try:
        return await ai_usage.start(
            request_id=request_id,
            endpoint=endpoint,
            stream=stream,
            key_id=key_id,
            key_name=key_name,
            model_id=model_id,
            model_alias=model_alias,
            provider_slug=provider_slug,
        )
    except AiAuditWriteError:
        raise AiGatewayError.upstream_error(error_type="audit_write_failed")


async def _audit_denied(
    ai_usage: AiUsageService,
    err: AiGatewayError,
    *,
    endpoint: str,
    stream: bool,
    request_id: str,
    key_id: int | None = None,
    key_name: str | None = None,
    model_id: int | None = None,
    model_alias: str | None = None,
    provider_slug: str | None = None,
    guardrail_hits: list[dict[str, Any]] | None = None,
) -> None:
    """拒绝类响应（401/403/404/429/护栏）：写一条 denied 审计事件。

    这条路径本就不转发上游，fail-closed 的"不转发"约束天然满足；审计写入尽力而为，
    失败只记日志——不能因为审计库抖动了连 401 都返回不了。
    """
    try:
        event_id = await ai_usage.start(
            request_id=request_id,
            endpoint=endpoint,
            stream=stream,
            key_id=key_id,
            key_name=key_name,
            model_id=model_id,
            model_alias=model_alias,
            provider_slug=provider_slug,
        )
        await ai_usage.complete(
            event_id,
            status="denied",
            denial_reason=err.code,
            error_type=err.error_type,
            guardrail_hits=guardrail_hits,
        )
    except Exception:  # noqa: BLE001 - denial 路径审计失败不应影响拒绝响应
        logger.exception("审计 denied 写入失败（denial 路径，不影响拒绝响应）")


# ── /v1/chat/completions ──────────────────────────────────────────

@router.post("/chat/completions")
async def chat_completions(request: Request):
    container = request.app.state.container
    raw = _extract_raw_key(request)
    snapshot = await container.ai_keys.verify(raw) if raw else None
    if snapshot is None:
        raise AiGatewayError.invalid_api_key()

    body = await request.json()
    stream = bool(body.get("stream"))
    alias = body.get("model")

    # ② 模型解析
    await container.ai_registry.snapshot()
    descriptor = container.ai_registry.resolve(alias)
    if descriptor is None:
        # 解析不到模型时只有 alias 可记，模型上下文留空
        err = AiGatewayError.model_not_found()
        await _audit_denied(
            container.ai_usage,
            err,
            endpoint="chat.completions",
            stream=stream,
            request_id=_request_id(request),
            key_id=snapshot.id,
            key_name=snapshot.name,
            model_alias=alias if isinstance(alias, str) else None,
        )
        raise err

    async def deny(err: AiGatewayError, hits: list[dict[str, Any]] | None = None) -> None:
        """③④⑤⑥ 的拒绝统一落审计（denial_reason 即 err.code）。

        这条路径不转发上游，fail-closed 天然满足；审计失败只记日志，不能因为
        审计抖动连拒绝响应都发不出去。
        """
        await _audit_denied(
            container.ai_usage,
            err,
            endpoint="chat.completions",
            stream=stream,
            request_id=_request_id(request),
            key_id=snapshot.id,
            key_name=snapshot.name,
            model_id=descriptor.model_id,
            model_alias=descriptor.alias,
            provider_slug=descriptor.provider_slug,
            guardrail_hits=hits,
        )

    # ③ 授权（deny-by-default）
    if descriptor.model_id not in snapshot.allowed_model_ids:
        err = AiGatewayError.permission_denied()
        await deny(err)
        raise err

    # ④ 配额
    async with session_scope() as session:
        if not await QuotaChecker().check(session, snapshot):
            err = AiGatewayError.insufficient_quota()
            await deny(err)
            raise err

    # ⑤ 限流
    if not container.ai_rate_limiter.allow(snapshot.id, snapshot.rate_limit_rpm):
        err = AiGatewayError.rate_limit_exceeded()
        await deny(err)
        raise err

    # ⑥ 请求侧护栏（命中即 block，且不透传上游）
    engine = await container.ai_guardrails.load()
    req_hits = engine.check(_request_guardrail_text(body, "chat.completions"), "request")
    if req_hits:
        hits = [_hit_dict(h) for h in req_hits]
        err = AiGatewayError.guardrail_blocked()
        await deny(err, hits)
        raise err

    # ⑦ 审计 start（fail-closed，必须在转发之前）
    event_id = await _start_audit(
        container.ai_usage,
        endpoint="chat.completions",
        stream=stream,
        request_id=_request_id(request),
        key_id=snapshot.id,
        key_name=snapshot.name,
        model_id=descriptor.model_id,
        model_alias=descriptor.alias,
        provider_slug=descriptor.provider_slug,
    )

    # ⑧ 转发：把对外 alias 换成上游真实模型名
    forward = dict(body)
    forward["model"] = descriptor.provider_model_name

    if stream:
        return await _stream_chat(request, descriptor, forward, event_id, snapshot, engine)
    return await _nonstream_chat(request, descriptor, forward, event_id, snapshot, engine)


async def _nonstream_chat(
    request: Request,
    descriptor: Any,
    forward: dict[str, Any],
    event_id: int,
    snapshot: AiKeySnapshot,
    engine: GuardrailEngine,
) -> Any:
    container = request.app.state.container
    ai_usage: AiUsageService = container.ai_usage
    try:
        resp = await container.ai_pool.post_json(
            base_url=descriptor.base_url,
            api_key=descriptor.auth.bearer_token or "",
            path=CHAT_PATH,
            json=forward,
        )
    except (httpx.TimeoutException, httpx.HTTPError) as exc:
        await ai_usage.complete(event_id, status="failed", error_type="upstream_error")
        raise AiGatewayError.upstream_error(error_type=_httpx_error_type(exc))

    if resp.status_code >= 500:
        await ai_usage.complete(
            event_id, status="failed", error_type="upstream_error", upstream_status_code=resp.status_code
        )
        raise AiGatewayError.upstream_error(error_type=f"upstream_http_{resp.status_code}")

    if resp.status_code != 200:
        # 上游 4xx：原样透传，不假装成网关错误
        await ai_usage.complete(
            event_id, status="failed", error_type="upstream_error", upstream_status_code=resp.status_code
        )
        return Response(
            content=resp.text,
            status_code=resp.status_code,
            media_type=resp.headers.get("content-type", "application/json"),
        )

    # ⑨ 响应 + 记账
    data = resp.json()
    usage = parse_usage(data)
    if usage is None:
        usage = estimate_usage(_response_text(data))

    # 非流式响应侧护栏命中 → block（§4.3）
    resp_hits = engine.check(_response_text(data), "response")
    if resp_hits:
        hits = [_hit_dict(h) for h in resp_hits]
        await ai_usage.complete(
            event_id,
            status="denied",
            denial_reason="guardrail_blocked",
            error_type="guardrail_blocked",
            usage=usage,
            guardrail_hits=hits,
        )
        raise AiGatewayError.guardrail_blocked()

    await ai_usage.complete(
        event_id, status="succeeded", usage=usage, upstream_status_code=resp.status_code
    )
    async with session_scope() as session:
        await record_daily(session, snapshot.id, usage)
    return data


async def _stream_chat(
    request: Request,
    descriptor: Any,
    forward: dict[str, Any],
    event_id: int,
    snapshot: AiKeySnapshot,
    engine: GuardrailEngine,
) -> StreamingResponse:
    container = request.app.state.container
    ai_usage: AiUsageService = container.ai_usage
    pool: AiUpstreamPool = container.ai_pool

    async def on_finish(
        usage: Usage | None,
        *,
        error_type: str | None = None,
        first_token_ms: int | None = None,
        guardrail_hits: list[dict[str, Any]] | None = None,
    ) -> None:
        # 流式响应侧只检测、不中断流：guardrail_hits 入审计即可
        status = "failed" if error_type else "succeeded"
        if usage is None:
            usage = _empty_usage()
        try:
            await ai_usage.complete(
                event_id,
                status=status,
                usage=usage,
                error_type=error_type,
                first_token_ms=first_token_ms,
                guardrail_hits=guardrail_hits,
                upstream_status_code=200,
            )
        except Exception:  # noqa: BLE001 - 流已发出，complete 失败不能影响客户端
            logger.exception("流式审计 complete 失败（不影响已发出的流）")
        if usage is not None:
            try:
                async with session_scope() as session:
                    await record_daily(session, snapshot.id, usage)
            except Exception:  # noqa: BLE001
                logger.exception("流式日汇总失败")

    body = prepare_stream_body(forward)
    t0 = time.monotonic()

    async def event_generator():
        async with pool.stream_sse(
            base_url=descriptor.base_url,
            api_key=descriptor.auth.bearer_token or "",
            path=CHAT_PATH,
            json=body,
        ) as upstream:
            async for item in relay_stream(
                upstream,
                on_finish,
                t0=t0,
                response_guardrail=lambda text: [
                    _hit_dict(h) for h in engine.check(text, "response")
                ],
            ):
                yield item

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ── /v1/embeddings ────────────────────────────────────────────────

@router.post("/embeddings")
async def embeddings(request: Request):
    container = request.app.state.container
    raw = _extract_raw_key(request)
    snapshot = await container.ai_keys.verify(raw) if raw else None
    if snapshot is None:
        raise AiGatewayError.invalid_api_key()

    body = await request.json()
    alias = body.get("model")

    await container.ai_registry.snapshot()
    descriptor = container.ai_registry.resolve(alias)
    # kind 不匹配视为模型不存在：embeddings 端点只接受 kind=embedding 的模型
    if descriptor is None or descriptor.kind != AI_MODEL_KIND_EMBEDDING:
        err = AiGatewayError.model_not_found()
        await _audit_denied(
            container.ai_usage,
            err,
            endpoint="embeddings",
            stream=False,
            request_id=_request_id(request),
            key_id=snapshot.id,
            key_name=snapshot.name,
            model_alias=alias if isinstance(alias, str) else None,
        )
        raise err

    async def deny(err: AiGatewayError, hits: list[dict[str, Any]] | None = None) -> None:
        """拒绝统一落审计（denial_reason 即 err.code）；审计失败只记日志。"""
        await _audit_denied(
            container.ai_usage,
            err,
            endpoint="embeddings",
            stream=False,
            request_id=_request_id(request),
            key_id=snapshot.id,
            key_name=snapshot.name,
            model_id=descriptor.model_id,
            model_alias=descriptor.alias,
            provider_slug=descriptor.provider_slug,
            guardrail_hits=hits,
        )

    if descriptor.model_id not in snapshot.allowed_model_ids:
        err = AiGatewayError.permission_denied()
        await deny(err)
        raise err

    async with session_scope() as session:
        if not await QuotaChecker().check(session, snapshot):
            err = AiGatewayError.insufficient_quota()
            await deny(err)
            raise err

    if not container.ai_rate_limiter.allow(snapshot.id, snapshot.rate_limit_rpm):
        err = AiGatewayError.rate_limit_exceeded()
        await deny(err)
        raise err

    engine = await container.ai_guardrails.load()
    req_hits = engine.check(_request_guardrail_text(body, "embeddings"), "request")
    if req_hits:
        hits = [_hit_dict(h) for h in req_hits]
        err = AiGatewayError.guardrail_blocked()
        await deny(err, hits)
        raise err

    event_id = await _start_audit(
        container.ai_usage,
        endpoint="embeddings",
        stream=False,
        request_id=_request_id(request),
        key_id=snapshot.id,
        key_name=snapshot.name,
        model_id=descriptor.model_id,
        model_alias=descriptor.alias,
        provider_slug=descriptor.provider_slug,
    )

    forward = dict(body)
    forward["model"] = descriptor.provider_model_name

    try:
        resp = await container.ai_pool.post_json(
            base_url=descriptor.base_url,
            api_key=descriptor.auth.bearer_token or "",
            path=EMBEDDINGS_PATH,
            json=forward,
        )
    except (httpx.TimeoutException, httpx.HTTPError) as exc:
        await container.ai_usage.complete(event_id, status="failed", error_type="upstream_error")
        raise AiGatewayError.upstream_error(error_type=_httpx_error_type(exc))

    if resp.status_code >= 500:
        await container.ai_usage.complete(
            event_id, status="failed", error_type="upstream_error", upstream_status_code=resp.status_code
        )
        raise AiGatewayError.upstream_error(error_type=f"upstream_http_{resp.status_code}")

    if resp.status_code != 200:
        return Response(
            content=resp.text,
            status_code=resp.status_code,
            media_type=resp.headers.get("content-type", "application/json"),
        )

    data = resp.json()
    # embeddings 上游 usage 只有 prompt/total：自行补 completion=0
    u = data.get("usage") or {}
    usage = Usage(
        prompt_tokens=int(u.get("prompt_tokens", 0)),
        completion_tokens=0,
        total_tokens=int(u.get("total_tokens", 0)),
        estimated=False,
    )
    await container.ai_usage.complete(
        event_id, status="succeeded", usage=usage, upstream_status_code=resp.status_code
    )
    async with session_scope() as session:
        await record_daily(session, snapshot.id, usage)
    return data


# ── /v1/models ───────────────────────────────────────────────────

@router.get("/models")
async def list_models(request: Request):
    container = request.app.state.container
    raw = _extract_raw_key(request)
    snapshot = await container.ai_keys.verify(raw) if raw else None
    if snapshot is None:
        raise AiGatewayError.invalid_api_key()

    await container.ai_registry.snapshot()
    data = []
    for alias, desc in container.ai_registry.descriptors().items():
        # 只返回该 Key 授权且启用的模型（enabled 已由快照过滤）
        if desc.model_id not in snapshot.allowed_model_ids:
            continue
        created = (
            int(calendar.timegm(desc.created_at.timetuple()))
            if desc.created_at is not None
            else _MODELS_CREATED_FALLBACK
        )
        data.append(
            {
                "id": desc.alias,
                "object": "model",
                "created": created,
                "owned_by": desc.provider_slug,
            }
        )
    return {"object": "list", "data": data}
