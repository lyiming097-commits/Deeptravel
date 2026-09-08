import json

import httpx
import pytest

from backend.app.llm.deepseek import DeepSeekClient


@pytest.mark.asyncio
async def test_deepseek_chat_stream_yields_sse_content_and_sets_stream_flag() -> None:
    requests: list[dict] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        body = (
            'data: {"choices":[{"delta":{"role":"assistant"}}]}\n\n'
            'data: {"choices":[{"delta":{"content":"你好"}}]}\n\n'
            'data: {"choices":[{"delta":{"content":"，旅行顾问在此。"}}]}\n\n'
            "data: [DONE]\n\n"
        )
        return httpx.Response(
            200,
            content=body.encode(),
            headers={"content-type": "text/event-stream"},
        )

    client = DeepSeekClient(
        "test-key",
        "https://api.deepseek.com",
        "deepseek-chat",
        transport=httpx.MockTransport(handler),
    )

    chunks = [chunk async for chunk in client.chat_stream([{"role": "user", "content": "你好"}])]

    assert "".join(chunks) == "你好，旅行顾问在此。"
    assert requests[0]["stream"] is True


@pytest.mark.asyncio
async def test_deepseek_chat_json_injects_required_json_instruction() -> None:
    requests: list[dict] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"destination":"洛阳"}'}}]},
        )

    client = DeepSeekClient(
        "test-key",
        "https://api.deepseek.com",
        "deepseek-chat",
        transport=httpx.MockTransport(handler),
    )

    result = await client.chat_json([{"role": "system", "content": "提取地点"}])

    assert result == {"destination": "洛阳"}
    assert requests[0]["response_format"] == {"type": "json_object"}
    assert "json" in requests[0]["messages"][0]["content"].lower()
