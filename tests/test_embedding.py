import json

import httpx
import pytest

from backend.app.rag.embedding import LocalHashEmbedding, OllamaEmbedding


@pytest.mark.asyncio
async def test_local_hash_embedding_is_deterministic_and_normalized() -> None:
    provider = LocalHashEmbedding(128)
    first, second = await provider.embed(["成都旅行攻略", "成都旅行攻略"])

    assert first == second
    assert len(first) == 128
    assert sum(value * value for value in first) == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_local_hash_embedding_keeps_related_text_closer() -> None:
    provider = LocalHashEmbedding(256)
    query, related, unrelated = await provider.embed(
        ["成都美食旅行", "成都旅行和美食攻略", "数据库索引维护"]
    )

    def similarity(left: list[float], right: list[float]) -> float:
        return sum(a * b for a, b in zip(left, right, strict=True))

    assert similarity(query, related) > similarity(query, unrelated)


@pytest.mark.asyncio
async def test_ollama_embedding_uses_native_api_batches_and_query_instruction() -> None:
    requests: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        requests.append(payload)
        return httpx.Response(
            200,
            json={"embeddings": [[1.0] + [0.0] * 31 for _ in payload["input"]]},
        )

    provider = OllamaEmbedding(
        "http://127.0.0.1:11434",
        "qwen3-embedding:0.6b",
        dimensions=32,
        batch_size=2,
        query_instruction="Retrieve travel passages",
        transport=httpx.MockTransport(handler),
    )

    documents = await provider.embed_documents(["成都", "杭州", "北京"])
    query = await provider.embed_query("成都亲子游")

    assert len(documents) == 3
    assert len(requests) == 3
    assert requests[0]["model"] == "qwen3-embedding:0.6b"
    assert requests[0]["dimensions"] == 32
    assert requests[-1]["input"] == [
        "Instruct: Retrieve travel passages\nQuery: 成都亲子游"
    ]
    assert len(query) == 32


@pytest.mark.asyncio
async def test_ollama_embedding_rejects_wrong_dimensions() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"embeddings": [[0.1, 0.2]]})
    )
    provider = OllamaEmbedding(
        "http://127.0.0.1:11434",
        "qwen3-embedding:0.6b",
        dimensions=32,
        transport=transport,
    )

    with pytest.raises(RuntimeError, match="数据库要求 32"):
        await provider.embed(["成都"])
