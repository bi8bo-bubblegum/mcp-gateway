"""内存假 OpenAI 兼容上游，供 AI 网关端到端测试使用（不触网）。

支持按故障模式注入异常，覆盖 M2/M3 的六类错误码与流式降级路径：
- ok（默认）：正常返回
- timeout：故意不返回，让客户端按超时失败
- http_500：直接回 500
- no_usage_in_stream：流式正常返回但最后一个 chunk 不带 usage（触发网关估算降级）
"""
from collections.abc import AsyncIterator

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

# 固定的用量样本，便于断言网关记账与上游一致
_PROMPT_TOKENS = 5
_COMPLETION_TOKENS = 7
_TOTAL_TOKENS = _PROMPT_TOKENS + _COMPLETION_TOKENS

_SSE_FIELDS = 'data: {"id":"chatcmpl-1","object":"chat.completion.chunk"'


def _sse_line(payload: dict) -> str:
    import json

    return f"data: {json.dumps(payload)}\n\n"


def make_upstream_app() -> FastAPI:
    app = FastAPI()
    # 由测试在调用前改写，控制故障模式
    app.state.mode = "ok"

    def _mode() -> str:
        return getattr(app.state, "mode", "ok")

    @app.post("/v1/chat/completions", response_model=None)
    async def chat_completions(request: Request):
        mode = _mode()
        if mode == "timeout":
            # 永不返回，让客户端按 ai_request_timeout 失败
            await request.body()
            await _hang()
            return {}  # unreachable

        body = await request.json()
        stream = bool(body.get("stream"))

        if mode == "http_500":
            from fastapi import HTTPException

            raise HTTPException(status_code=500, detail="upstream boom")

        if not stream:
            return {
                "id": "chatcmpl-1",
                "object": "chat.completion",
                "created": 1700000000,
                "model": body.get("model", "gpt-4o-mini"),
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "Hello"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": _PROMPT_TOKENS,
                    "completion_tokens": _COMPLETION_TOKENS,
                    "total_tokens": _TOTAL_TOKENS,
                },
            }

        # 流式：逐 chunk 透传，最后一块带 usage
        async def event_stream() -> AsyncIterator[str]:
            yield _sse_line(
                {
                    "id": "chatcmpl-1",
                    "object": "chat.completion.chunk",
                    "created": 1700000000,
                    "model": body.get("model", "gpt-4o-mini"),
                    "choices": [
                        {"index": 0, "delta": {"content": "Hello"}, "finish_reason": None}
                    ],
                }
            )
            if mode == "no_usage_in_stream":
                # 某些中转不认 stream_options.include_usage，最后一个 chunk 无 usage，
                # 网关应降级为字符估算并置 usage_estimated=true
                yield _sse_line(
                    {
                        "id": "chatcmpl-1",
                        "object": "chat.completion.chunk",
                        "created": 1700000000,
                        "model": body.get("model", "gpt-4o-mini"),
                        "choices": [
                            {"index": 0, "delta": {}, "finish_reason": "stop"}
                        ],
                    }
                )
            else:
                yield _sse_line(
                    {
                        "id": "chatcmpl-1",
                        "object": "chat.completion.chunk",
                        "created": 1700000000,
                        "model": body.get("model", "gpt-4o-mini"),
                        "choices": [
                            {"index": 0, "delta": {}, "finish_reason": "stop"}
                        ],
                        "usage": {
                            "prompt_tokens": _PROMPT_TOKENS,
                            "completion_tokens": _COMPLETION_TOKENS,
                            "total_tokens": _TOTAL_TOKENS,
                        },
                    }
                )
            yield "data: [DONE]\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @app.post("/v1/embeddings")
    async def embeddings(request: Request) -> dict:
        body = await request.json()
        if _mode() == "http_500":
            from fastapi import HTTPException

            raise HTTPException(status_code=500, detail="upstream boom")
        return {
            "object": "list",
            "data": [
                {
                    "object": "embedding",
                    "index": 0,
                    "embedding": [0.1, 0.2, 0.3],
                }
            ],
            "model": body.get("model", "text-embedding"),
            "usage": {
                "prompt_tokens": 3,
                "total_tokens": 3,
            },
        }

    @app.get("/v1/models")
    async def list_models() -> dict:
        if _mode() == "http_500":
            from fastapi import HTTPException

            raise HTTPException(status_code=500, detail="upstream boom")
        return {
            "object": "list",
            "data": [
                {
                    "id": "gpt-4o-mini",
                    "object": "model",
                    "created": 1700000000,
                    "owned_by": "openai",
                },
                {
                    "id": "text-embedding-3-small",
                    "object": "model",
                    "created": 1700000000,
                    "owned_by": "openai",
                },
            ],
        }

    return app


async def _hang() -> None:
    # 永远挂起，模拟上游超时
    await _never()


async def _never() -> None:
    import asyncio

    await asyncio.sleep(10**9)
