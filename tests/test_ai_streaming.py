"""relay_stream + prepare_stream_body 单元测试（不触网，纯内存假流）。

覆盖 §4.2：注入 stream_options.include_usage、SSE 原样透传、usage 提取、无 usage
降级估算、响应侧护栏旁路收集、客户端断连标记 cancelled。
"""
import pytest

from app.ai.streaming import prepare_stream_body, relay_stream


class _FakeUpstream:
    """最小可迭代字节流，满足 relay_stream 所需的 aiter_bytes 协议。"""

    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    async def aiter_bytes(self):
        for c in self._chunks:
            yield c


# ── prepare_stream_body（请求侧注入）─────────────────────────────────

def test_injects_stream_options_include_usage():
    body = {"model": "gpt", "stream": True}
    out = prepare_stream_body(body)
    # 注入 include_usage=True
    assert out["stream_options"]["include_usage"] is True
    # 原 body 的其它字段不动
    assert out["model"] == "gpt"
    assert out["stream"] is True
    # 不 mutate 原始入参（调用方可能还要用）
    assert "stream_options" not in body


# ── relay_stream 行为 ───────────────────────────────────────────────

async def test_sse_chunks_forwarded_verbatim():
    chunks = [
        b'data: {"choices":[{"delta":{"content":"He"}}]}\n\n',
        b'data: {"choices":[{"delta":{},"finish_reason":"stop"}],'
        b'"usage":{"prompt_tokens":5,"completion_tokens":7,"total_tokens":12}}\n\n',
        b"data: [DONE]\n\n",
    ]
    result: dict = {}
    out = [c async for c in relay_stream(_FakeUpstream(chunks), _make_on_finish(result))]
    # 字节原样透传，一个不多一个不少
    assert out == chunks
    assert result["usage"].prompt_tokens == 5
    assert result["usage"].total_tokens == 12
    assert result["first_token_ms"] is not None


async def test_usage_extracted_from_final_chunk():
    chunk = (
        b'data: {"usage":{"prompt_tokens":1,"completion_tokens":2,"total_tokens":3}}\n\n'
    )
    result: dict = {}
    _ = [c async for c in relay_stream(_FakeUpstream([chunk]), _make_on_finish(result))]
    assert result["usage"].prompt_tokens == 1
    assert result["usage"].completion_tokens == 2
    assert result["usage"].estimated is False


async def test_no_usage_falls_back_to_estimate():
    # 最后一个 chunk 不带 usage（某些中转不认 stream_options），应降级估算
    chunks = [
        b'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\n',
        b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n',
        b"data: [DONE]\n\n",
    ]
    result: dict = {}
    _ = [c async for c in relay_stream(_FakeUpstream(chunks), _make_on_finish(result))]
    # 估算必须标记 estimated=True，诚实说明不是精确值
    assert result["usage"].estimated is True
    # 估算按字符数：len("Hello")=5 → ceil(5/4)=2
    assert result["usage"].completion_tokens == 2
    assert result["usage"].total_tokens == 2


async def test_response_guardrail_collected_but_not_blocking():
    # 流式响应侧只检测入审计、不中断流（§4.3）
    chunk = (
        b'data: {"choices":[{"delta":{"content":"badword"}}],'
        b'"usage":{"prompt_tokens":1,"completion_tokens":1,"total_tokens":2}}\n\n'
    )
    hits_out: list = []

    def checker(text: str) -> list[dict]:
        if "badword" in text:
            return [{"rule_id": 1, "rule_name": "r"}]
        return []

    result: dict = {}

    async def on_finish(usage, *, error_type=None, first_token_ms=None, guardrail_hits=None):
        result["guardrail_hits"] = guardrail_hits

    out = [c async for c in relay_stream(_FakeUpstream([chunk]), on_finish, response_guardrail=checker)]
    assert len(out) == 1  # 流未被中断
    assert result["guardrail_hits"] == [{"rule_id": 1, "rule_name": "r"}]


async def test_disconnect_marks_cancelled():
    # 客户端断连（GeneratorExit）→ 记账 status=failed, error_type=cancelled
    chunk = b'data: {"choices":[{"delta":{"content":"Hi"}}]}\n\n'
    result: dict = {}

    async def on_finish(usage, *, error_type=None, first_token_ms=None, guardrail_hits=None):
        result["error_type"] = error_type
        result["usage"] = usage

    gen = relay_stream(_FakeUpstream([chunk]), on_finish)
    await gen.__anext__()  # 消费首个 chunk
    with pytest.raises(GeneratorExit):
        # 模拟客户端断开：向生成器注入 GeneratorExit
        await gen.athrow(GeneratorExit())
    assert result["error_type"] == "cancelled"
    assert result["usage"] is not None


def _make_on_finish(store: dict):
    async def on_finish(usage, *, error_type=None, first_token_ms=None, guardrail_hits=None):
        store["usage"] = usage
        store["first_token_ms"] = first_token_ms

    return on_finish
