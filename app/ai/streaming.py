"""SSE 透传与流式计量。

设计文档 §3.1 / §4.2 / §4.3。职责极窄：把上游 SSE 字节流**原样**转给客户端，同时
旁路（不阻断）解析 `data: {...}` 取出 usage；流式下我们主动在请求侧注入
`stream_options.include_usage=True`（见 prepare_stream_body），上游最后一个 chunk
带回 usage 就直接用，不带则降级为字符估算并标记 estimated。

响应侧护栏：流式只检测入审计、不中断流（§4.3），故 relay_stream 接受可选
response_guardrail 回调，逐 chunk 扫描并把命中累积传给记账回调。

时间两侧约定见 metering / quota 注释；首 token 时延在收到第一个 chunk 时测一次。
"""
import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from typing import Any

from app.ai.metering import Usage, estimate_usage, parse_usage
from app.ai.upstream import AiUpstreamPool

# 流式请求侧转发前注入的参数；上游不认该参数也不能报错（§4.2 降级估算路径）
def prepare_stream_body(body: dict[str, Any]) -> dict[str, Any]:
    """流式转发前注入 stream_options.include_usage=True，且不动原始 body 其余字段。

    有些中转不认 stream_options，但那是"上游回不回 usage"的问题，不是"我们多传
    一个参数就崩"的问题——多传一个 JSON 键对合规 OpenAI 端点无害，故直接注入即可，
    降级由 relay_stream 在收不到 usage 时处理。
    """
    payload = dict(body)
    opts = dict(payload.get("stream_options") or {})
    opts["include_usage"] = True
    payload["stream_options"] = opts
    return payload


def _payload_content(payload: dict[str, Any]) -> str:
    """从一段 SSE data 载荷里抽取文本（chat 的 delta/message.content）。"""
    parts: list[str] = []
    for choice in payload.get("choices", []) or []:
        delta = choice.get("delta") or choice.get("message") or {}
        content = delta.get("content")
        if isinstance(content, str) and content:
            parts.append(content)
    return "".join(parts)


async def relay_stream(
    upstream: Any,
    on_finish: Callable[..., Awaitable[None]],
    *,
    t0: float | None = None,
    response_guardrail: Callable[[str], list[dict[str, Any]]] | None = None,
) -> Any:
    """逐块透传上游 SSE，旁路解析 usage 与响应侧护栏，结束后回调记账。

    upstream 只需提供 `aiter_bytes()`（httpx.Response 即满足）。on_finish 签名：
        async def on_finish(usage, *, error_type=None, first_token_ms=None, guardrail_hits=None)
    异常分支：客户端断连（GeneratorExit/CancelledError）→ status=failed, error_type=cancelled；
    上游中途异常 → 同上但 error_type=upstream_error。两种情况都按已收到的 usage 或估算落账。
    """
    start = t0 if t0 is not None else time.monotonic()
    first_token_ms: int | None = None
    buf = ""          # 尚未拼成完整行的残留
    content_buf = ""  # 已抽取的 delta 文本，用于降级估算
    usage: Usage | None = None
    seen_hits: list[dict[str, Any]] = []

    def _collect_hits(text: str) -> None:
        if response_guardrail is None or not text:
            return
        for hit in response_guardrail(text):
            rid = hit.get("rule_id")
            if not any(h.get("rule_id") == rid for h in seen_hits):
                seen_hits.append(hit)

    try:
        async for chunk in upstream.aiter_bytes():
            if first_token_ms is None:
                # 收到第一个 chunk 即记首 token 时延（流式体验指标，§4.2）
                first_token_ms = int((time.monotonic() - start) * 1000)
            yield chunk

            buf += chunk.decode("utf-8", errors="replace")
            # 逐行解析：只有完整行才处理，避免把半截 data 当成 JSON
            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                line = line.rstrip("\r")
                if not line.startswith("data:"):
                    continue
                data = line[len("data:"):].strip()
                if data == "[DONE]":
                    continue
                try:
                    payload = json.loads(data)
                except json.JSONDecodeError:
                    continue
                parsed = parse_usage(payload)
                if parsed is not None:
                    usage = parsed
                content_buf += _payload_content(payload)
                _collect_hits(_payload_content(payload))

        # 正常结束：有 usage 用上游的，没有就降级估算（诚实标记为 estimated）
        if usage is None:
            usage = estimate_usage(content_buf)
        await on_finish(
            usage,
            error_type=None,
            first_token_ms=first_token_ms,
            guardrail_hits=list(seen_hits),
        )
    except (GeneratorExit, asyncio.CancelledError):
        # 客户端断连 / 任务被取消：已产生用量按已收到的或估算记账，状态 failed(cancelled)
        if usage is None:
            usage = estimate_usage(content_buf)
        await on_finish(
            usage,
            error_type="cancelled",
            first_token_ms=first_token_ms,
            guardrail_hits=list(seen_hits),
        )
        raise
    except Exception:
        if usage is None:
            usage = estimate_usage(content_buf)
        await on_finish(
            usage,
            error_type="upstream_error",
            first_token_ms=first_token_ms,
            guardrail_hits=list(seen_hits),
        )
        raise


def _empty_usage() -> Usage:
    return Usage(prompt_tokens=0, completion_tokens=0, total_tokens=0, estimated=True)


# 便于外部（router）在异常早退时也有可用的占位 usage
__all__ = ["relay_stream", "prepare_stream_body", "_empty_usage", "AiUpstreamPool"]
