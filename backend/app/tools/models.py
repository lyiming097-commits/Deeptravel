from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class EvidenceItem:
    """RAG 与公网检索共用的标准化证据。"""

    content: str
    title: str
    url: str | None
    source_type: str
    similarity: float
    metadata: dict[str, Any] = field(default_factory=dict)
    chunk_id: str | None = None

    def citation(self) -> dict[str, Any]:
        return {
            "type": self.source_type,
            "chunk_id": self.chunk_id,
            "title": self.title,
            "url": self.url,
            "similarity": round(self.similarity, 4),
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class SemanticSearchResult:
    items: list[EvidenceItem]
    tools_used: list[str]
