from dataclasses import dataclass
from typing import Any

from backend.app.config import Settings
from backend.app.rag.embedding import EmbeddingProvider, build_embedding_provider
from backend.app.rag.pgvector_store import PgVectorStore


@dataclass(frozen=True)
class RetrievedChunk:
    id: str
    content: str
    source: str
    source_url: str | None
    similarity: float
    metadata: dict[str, Any]


class RagRetriever:
    def __init__(
        self,
        settings: Settings,
        embedding: EmbeddingProvider | None = None,
        store: PgVectorStore | None = None,
    ) -> None:
        self.settings = settings
        self.embedding = embedding or build_embedding_provider(settings)
        self.store = store or PgVectorStore()

    async def search(
        self, query: str, top_k: int | None = None, *, category: str | None = None,
        sub_category: str | None = None, city: str | None = None,
        province: str | None = None, season: str | None = None,
        travel_type: str | None = None,
    ) -> list[RetrievedChunk]:
        if not query.strip():
            return []
        query_embedding = await self.embedding.embed_query(query)
        try:
            rows = await self.store.similarity_search(
                query_embedding, top_k=top_k or self.settings.rag_top_k,
                category=category, sub_category=sub_category, city=city,
                province=province, season=season, travel_type=travel_type,
            )
        except TypeError:
            # Keep small test doubles and external integrations compatible.
            rows = await self.store.similarity_search(
                query_embedding, top_k=top_k or self.settings.rag_top_k,
                category=category, city=city,
            )
        return [
            RetrievedChunk(
                id=str(row["id"]),
                content=row["content"],
                source=row["file_name"],
                source_url=row["source_url"],
                similarity=float(row["similarity"]),
                metadata=row["metadata"] or {},
            )
            for row in rows
        ]
