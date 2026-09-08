import asyncio
import logging
import math
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

import httpx

from backend.app.config import Settings
from backend.app.mcp.client import McpClient
from backend.app.rag.embedding import EmbeddingProvider
from backend.app.rag.ingestion import split_text
from backend.app.tools.models import EvidenceItem, SemanticSearchResult
from backend.app.tools.relevance import (
    SearchIntent,
    classify_search_intent,
    filter_evidence_items,
    infer_search_destination,
)

logger = logging.getLogger(__name__)


class PageSource(Protocol):
    async def search_and_fetch(
        self, query: str, max_results: int = 5
    ) -> list[dict[str, Any]]: ...


class BrowserSearchTool:
    """Search MCP 搜索与网页正文抓取工具。"""

    tool_names = ("web_search", "web_fetch")

    def __init__(self, client: McpClient, max_pages: int = 3) -> None:
        self.client = client
        self.max_pages = max_pages

    async def search_and_fetch(
        self, query: str, max_results: int = 5
    ) -> list[dict[str, Any]]:
        response = await self.client.call_tool(
            "web_search", {"query": query, "max_results": max_results}
        )
        results = response.get("results", [])
        async def fetch_one(result: dict[str, Any]) -> dict[str, Any] | None:
            if not isinstance(result, dict) or not result.get("url"):
                return None
            page = dict(result)
            try:
                fetched = await self.client.call_tool(
                    "web_fetch", {"url": result["url"], "max_chars": 20000}
                )
                if not isinstance(fetched, dict):
                    return None
                content = str(fetched.get("content") or "").strip()
                # Search snippets are discovery metadata, not extracted page
                # content.  Do not pass them to the answer model when a page
                # cannot be fetched; this keeps the public-search contract
                # grounded in actual webpage text.
                if not content:
                    return None
                page.update(
                    {
                        "title": fetched.get("title") or result.get("title"),
                        "url": fetched.get("final_url") or result.get("url"),
                        "content": content,
                        # Keep image observations alongside the extracted
                        #正文.  They are matched to named POIs later; URLs are
                        # never exposed to the answer model as instructions.
                        "images": (
                            fetched.get("images")
                            or result.get("images")
                            or result.get("image")
                            or result.get("thumbnail")
                            or []
                        ),
                        "renderer": fetched.get("renderer"),
                        "fetched_at": fetched.get("fetched_at"),
                    }
                )
            except (httpx.HTTPError, RuntimeError, ValueError):
                # A URL without a successfully extracted body is not evidence
                # for the model.  Keep searching the remaining candidates.
                return None
            return page if str(page.get("content", "")).strip() else None

        # Fetch independent result pages concurrently.  ``gather`` preserves
        # search ranking order, while the Search MCP server still enforces its
        # own Playwright semaphore for the actual browser work.
        fetched_pages = await asyncio.gather(
            *(fetch_one(result) for result in results[: self.max_pages])
        )
        return [page for page in fetched_pages if page is not None]


class SemanticWebSearchTool:
    """网页证据：搜索、抓取、向量化和重排，并提交少量候选进入知识库。"""

    live_tool_names = ("web_search", "web_fetch", "semantic_rerank")
    tool_names = live_tool_names

    def __init__(
        self,
        settings: Settings,
        embedding: EmbeddingProvider,
        page_source: PageSource,
        candidate_sink: Callable[[list[EvidenceItem], list[list[float]]], Awaitable[int]] | None = None,
    ) -> None:
        self.settings = settings
        self.embedding = embedding
        self.page_source = page_source
        self.candidate_sink = candidate_sink

    async def search(
        self,
        query: str,
        *,
        intent: SearchIntent | None = None,
        destination: str | None = None,
    ) -> SemanticSearchResult:
        """Return ranked evidence and best-effort persist top candidates.

        Only the top-ranked one or two extracted chunks are persisted.  They
        are tagged with source/update metadata and can be edited or deleted by
        an administrator; volatile categories also receive a document TTL.
        """

        intent = intent or classify_search_intent(query)
        candidate_category = {
            "新闻": "travel_updates", "资讯": "travel_updates", "活动": "notices_events", "节假日": "notices_events",
            "开放": "notices_events", "开园": "notices_events", "攻略": "trip_plans", "行程": "trip_plans",
            "交通动态": "travel_updates",
            "交通": "transportation",
        }
        category = next((value for term, value in candidate_category.items() if term in query), None)
        destination = (
            infer_search_destination(query) if destination is None else destination
        )
        # Search and fetch first so every user question genuinely attempts the
        # live web pipeline.  Query embedding used to run before this call,
        # which meant a stopped Ollama service silently prevented DuckDuckGo
        # from being contacted at all.
        try:
            pages = await self.page_source.search_and_fetch(
                query, max_results=max(5, self.settings.web_rerank_top_k)
            )
        except (httpx.HTTPError, RuntimeError, ValueError):
            return SemanticSearchResult([], list(self.live_tool_names))
        try:
            query_vector = await self.embedding.embed_query(query)
        except (httpx.HTTPError, RuntimeError, ValueError):
            # Do not pass arbitrary, unranked snippets to the model when the
            # semantic ranker is unavailable.  The web request was still made,
            # and a later request can recover as soon as Ollama is healthy.
            return SemanticSearchResult([], list(self.live_tool_names))
        candidates: list[dict[str, Any]] = []
        for page in pages:
            page_evidence = EvidenceItem(
                content=str(page.get("content", "")),
                title=str(page.get("title") or page.get("url") or "外部网页"),
                url=str(page.get("url")) if page.get("url") else None,
                source_type="external_web",
                similarity=0.0,
                metadata={
                    "snippet": page.get("snippet"),
                    "source_title": page.get("source_title"),
                    "source_domain": page.get("source_domain"),
                    "images": page.get("images") or [],
                },
            )
            if not filter_evidence_items([page_evidence], intent, destination):
                continue
            chunks = split_text(str(page.get("content", "")), chunk_size=800, overlap=100)
            for chunk in chunks[:8]:
                candidates.append({**page, "content": chunk["content"]})
        if not candidates:
            return SemanticSearchResult([], list(self.live_tool_names))
        try:
            vectors = await self.embedding.embed_documents(
                [str(candidate["content"]) for candidate in candidates]
            )
        except (httpx.HTTPError, RuntimeError, ValueError):
            return SemanticSearchResult([], list(self.live_tool_names))
        ranked = sorted(
            zip(candidates, vectors, strict=True),
            key=lambda item: self._cosine(query_vector, item[1]),
            reverse=True,
        )
        # Return at most one chunk per URL.  This keeps Top-K semantically
        # distinct pages and prevents duplicate links for adjacent chunks.
        selected: list[tuple[dict[str, Any], list[float]]] = []
        seen_pages: set[str] = set()
        for candidate, vector in ranked:
            page_key = str(candidate.get("url") or candidate.get("title") or "")
            if page_key in seen_pages:
                continue
            seen_pages.add(page_key)
            selected.append((candidate, vector))
            if len(selected) >= self.settings.web_rerank_top_k:
                break
        selected_sub_category = category or {"restaurant": "food"}.get(intent, intent)
        selected_sub_category = {
            "attraction": "destination_info", "city_intro": "destination_info", "culture_history": "destination_info",
            "one_day": "trip_plans", "three_day": "trip_plans", "family_trip": "trip_plans", "self_drive": "trip_plans",
            "travel_guide": "trip_plans", "hotel": "accommodation", "lodging_experience": "accommodation",
            "avoid_pitfalls": "practical_tips", "budget": "practical_tips", "faq": "practical_tips", "photography": "practical_tips",
            "opening": "notices_events", "festival": "notices_events", "traffic_update": "travel_updates", "news": "travel_updates",
        }.get(selected_sub_category, selected_sub_category)
        if selected_sub_category in {"guide", "general"}:
            selected_sub_category = ""
        live_items = [
            EvidenceItem(
                content=str(candidate["content"]),
                title=str(candidate.get("title") or candidate.get("url") or "外部网页"),
                url=str(candidate.get("url")) if candidate.get("url") else None,
                source_type="external_web",
                similarity=self._cosine(query_vector, vector),
                metadata={
                    "category": {
                        "attraction": "destination", "destination_info": "destination", "hotel": "food_lodging_transport",
                        "restaurant": "food_lodging_transport",
                        "food": "food_lodging_transport", "transportation": "food_lodging_transport",
                    "guide": "travel_guide", "travel_guide": "travel_guide", "trip_plans": "travel_guide",
                    "news": "travel_news", "travel_updates": "travel_news", "festival": "travel_news", "notices_events": "travel_news",
                    }.get(category or {"restaurant": "food"}.get(intent, intent), category or intent),
                    "sub_category": selected_sub_category,
                    "city": destination or "",
                    "provider": candidate.get("provider", "search_mcp"),
                    "renderer": candidate.get("renderer"),
                    "fetched_at": candidate.get("fetched_at"),
                    "snippet": candidate.get("snippet"),
                    "images": candidate.get("images") or [],
                },
            )
            for candidate, vector in selected
        ]
        if self.candidate_sink and live_items:
            # Store only the two most relevant chunks for administrator review;
            # persistence failures must not make a live search fail.
            try:
                top_items = live_items[:2]
                top_vectors = [vector for _, vector in selected[:2]]
                await self.candidate_sink(top_items, top_vectors)
            except Exception:
                logger.debug("保存公网候选失败", exc_info=True)
        return SemanticSearchResult(
            live_items,
            list(self.live_tool_names),
        )

    @staticmethod
    def _cosine(left: list[float], right: list[float]) -> float:
        numerator = sum(a * b for a, b in zip(left, right, strict=True))
        left_norm = math.sqrt(sum(value * value for value in left))
        right_norm = math.sqrt(sum(value * value for value in right))
        return numerator / (left_norm * right_norm) if left_norm and right_norm else 0.0
