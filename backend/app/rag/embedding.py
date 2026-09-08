import hashlib
import math
import re
from collections.abc import Sequence

import httpx

from backend.app.config import Settings


class EmbeddingProvider:
    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        raise NotImplementedError

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return await self.embed(texts)

    async def embed_query(self, text: str) -> list[float]:
        return (await self.embed([text]))[0]


class LocalHashEmbedding(EmbeddingProvider):
    """Deterministic local embedding for development and pipeline verification.

    This is not a semantic model. Production RAG should use BGE-M3 or another
    configured embedding service.
    """

    def __init__(self, dimensions: int = 1024) -> None:
        if dimensions < 32:
            raise ValueError("向量维度不能小于 32")
        self.dimensions = dimensions

    @staticmethod
    def _tokens(text: str) -> list[str]:
        normalized = re.sub(r"\s+", "", text.lower())
        latin_words = re.findall(r"[a-z0-9]+", normalized)
        chinese = "".join(re.findall(r"[\u4e00-\u9fff]", normalized))
        chinese_tokens = list(chinese) + [chinese[i : i + 2] for i in range(len(chinese) - 1)]
        return latin_words + chinese_tokens

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for token in self._tokens(text):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(value * value for value in vector))
        return [value / norm for value in vector] if norm else vector

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]


class OpenAICompatibleEmbedding(EmbeddingProvider):
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        dimensions: int,
        timeout: float = 30,
    ) -> None:
        if not base_url or not api_key:
            raise RuntimeError("Embedding API 地址或密钥未配置")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.dimensions = dimensions
        self.timeout = timeout

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        headers = {"Authorization": f"Bearer {self.api_key}"}
        payload = {"model": self.model, "input": list(texts)}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/embeddings", headers=headers, json=payload
            )
            response.raise_for_status()
            data = response.json().get("data", [])
        vectors = [item["embedding"] for item in sorted(data, key=lambda item: item["index"])]
        if len(vectors) != len(texts):
            raise RuntimeError("Embedding API 返回的向量数量不正确")
        if any(len(vector) != self.dimensions for vector in vectors):
            raise RuntimeError(f"Embedding 向量维度必须为 {self.dimensions}")
        return vectors


class OllamaEmbedding(EmbeddingProvider):
    def __init__(
        self,
        base_url: str,
        model: str,
        dimensions: int = 1024,
        timeout: float = 60,
        batch_size: int = 16,
        keep_alive: str = "10m",
        query_instruction: str = "",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not base_url:
            raise RuntimeError("EMBEDDING_BASE_URL 未配置")
        if not model:
            raise RuntimeError("EMBEDDING_MODEL 未配置")
        if dimensions < 32:
            raise ValueError("向量维度不能小于 32")
        if batch_size < 1:
            raise ValueError("Embedding 批量大小不能小于 1")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.dimensions = dimensions
        self.timeout = timeout
        self.batch_size = batch_size
        self.keep_alive = keep_alive
        self.query_instruction = query_instruction.strip()
        self.transport = transport

    async def _embed_batch(
        self, client: httpx.AsyncClient, texts: Sequence[str]
    ) -> list[list[float]]:
        payload = {
            "model": self.model,
            "input": list(texts),
            "dimensions": self.dimensions,
            "truncate": True,
            "keep_alive": self.keep_alive,
        }
        try:
            response = await client.post(f"{self.base_url}/api/embed", json=payload)
            response.raise_for_status()
        except httpx.ConnectError as exc:
            raise RuntimeError("无法连接 Ollama，请确认服务已在 11434 端口启动") from exc
        except httpx.TimeoutException as exc:
            raise RuntimeError("Ollama 向量化超时") from exc
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:300]
            if exc.response.status_code == 404:
                message = f"Ollama 模型不存在，请先执行：ollama pull {self.model}"
            else:
                message = f"Ollama 向量化失败（HTTP {exc.response.status_code}）：{detail}"
            raise RuntimeError(message) from exc
        vectors = response.json().get("embeddings", [])
        if len(vectors) != len(texts):
            raise RuntimeError("Ollama 返回的向量数量不正确")
        if any(len(vector) != self.dimensions for vector in vectors):
            actual = len(vectors[0]) if vectors else 0
            raise RuntimeError(f"Ollama 向量维度为 {actual}，数据库要求 {self.dimensions}")
        return vectors

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        values = list(texts)
        if not values:
            return []
        vectors: list[list[float]] = []
        async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
            for start in range(0, len(values), self.batch_size):
                vectors.extend(
                    await self._embed_batch(client, values[start : start + self.batch_size])
                )
        return vectors

    async def embed_query(self, text: str) -> list[float]:
        query = text
        if self.query_instruction:
            query = f"Instruct: {self.query_instruction}\nQuery: {text}"
        return (await self.embed([query]))[0]


def build_embedding_provider(settings: Settings) -> EmbeddingProvider:
    if settings.embedding_provider == "local_hash":
        return LocalHashEmbedding(settings.embedding_dimensions)
    if settings.embedding_provider == "ollama":
        return OllamaEmbedding(
            settings.embedding_base_url,
            settings.embedding_model,
            settings.embedding_dimensions,
            settings.embedding_timeout_seconds,
            settings.embedding_batch_size,
            settings.embedding_keep_alive,
            settings.embedding_query_instruction,
        )
    return OpenAICompatibleEmbedding(
        settings.embedding_base_url,
        settings.embedding_api_key,
        settings.embedding_model,
        settings.embedding_dimensions,
    )


async def embedding_health(settings: Settings) -> dict[str, str | bool | int | None]:
    if settings.embedding_provider == "local_hash":
        return {
            "provider": "local_hash",
            "connected": True,
            "model": "development-only",
            "dimensions": settings.embedding_dimensions,
        }
    if settings.embedding_provider != "ollama":
        return {
            "provider": settings.embedding_provider,
            "connected": bool(settings.embedding_base_url and settings.embedding_api_key),
            "model": settings.embedding_model,
            "dimensions": settings.embedding_dimensions,
        }
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            response = await client.get(f"{settings.embedding_base_url.rstrip('/')}/api/tags")
            response.raise_for_status()
        models = {item.get("name") for item in response.json().get("models", [])}
        available = settings.embedding_model in models
        return {
            "provider": "ollama",
            "connected": True,
            "model": settings.embedding_model,
            "model_available": available,
            "dimensions": settings.embedding_dimensions,
        }
    except httpx.HTTPError as exc:
        return {
            "provider": "ollama",
            "connected": False,
            "model": settings.embedding_model,
            "model_available": False,
            "dimensions": settings.embedding_dimensions,
            "error": exc.__class__.__name__,
        }
