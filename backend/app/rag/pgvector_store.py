from typing import Any

from sqlalchemy import text

from backend.app.database import session_scope


class PgVectorStore:
    async def similarity_search(
        self, query_embedding: list[float], top_k: int = 5,
        *, category: str | None = None, sub_category: str | None = None,
        city: str | None = None, province: str | None = None,
        season: str | None = None, travel_type: str | None = None,
    ) -> list[dict[str, Any]]:
        vector = "[" + ",".join(f"{value:.8f}" for value in query_embedding) + "]"
        async with session_scope() as session:
            rows = (
                (
                    await session.execute(
                        text(
                            """
                        SELECT c.id, c.content, c.metadata, d.file_name, d.source_url,
                               1 - (c.embedding <=> CAST(:embedding AS vector)) AS similarity
                        FROM knowledge_chunk c
                        JOIN knowledge_document d ON d.id = c.document_id
                        WHERE d.status = 'READY' AND d.enabled = true
                          AND (d.expires_at IS NULL OR d.expires_at > now())
                          AND c.embedding IS NOT NULL
                          -- Explicit casts are required by asyncpg when a
                          -- nullable bind appears first in an ``IS NULL``
                          -- branch; without them PostgreSQL reports
                          -- AmbiguousParameterError before executing the
                          -- vector search.
                          AND (CAST(:category AS text) IS NULL OR CAST(:category AS text) = ''
                               OR c.metadata->>'category' = CAST(:category AS text))
                          AND (CAST(:sub_category AS text) IS NULL OR CAST(:sub_category AS text) = ''
                               OR c.metadata->>'sub_category' = CAST(:sub_category AS text))
                          AND (CAST(:city AS text) IS NULL
                               OR CAST(:city AS text) = ''
                               OR c.metadata->>'city' = CAST(:city AS text))
                          AND (CAST(:province AS text) IS NULL OR CAST(:province AS text) = ''
                               OR c.metadata->>'province' = CAST(:province AS text))
                          AND (CAST(:season AS text) IS NULL OR CAST(:season AS text) = ''
                               OR c.metadata->>'season' = CAST(:season AS text))
                          AND (CAST(:travel_type AS text) IS NULL OR CAST(:travel_type AS text) = ''
                               OR c.metadata->>'travel_type' = CAST(:travel_type AS text))
                        ORDER BY c.embedding <=> CAST(:embedding AS vector)
                        LIMIT :top_k
                        """
                        ),
                        {"embedding": vector, "top_k": top_k, "category": category,
                         "sub_category": sub_category, "city": city, "province": province,
                         "season": season, "travel_type": travel_type},
                    )
                )
                .mappings()
                .all()
            )
        return [dict(row) for row in rows]
