from backend.app.config import Settings
from backend.app.rag.retriever import RagRetriever
from backend.app.tools.models import EvidenceItem
from backend.app.tools.relevance import (
    classify_search_intent,
    infer_search_destination,
    is_destination_compatible,
)


class RagSearchTool:
    """Agent 可调用的 PGVector RAG 工具。"""

    name = "rag_search"

    def __init__(self, settings: Settings, retriever: RagRetriever) -> None:
        self.settings = settings
        self.retriever = retriever

    async def search(
        self, query: str, *, category: str | None = None, sub_category: str | None = None,
        city: str | None = None, province: str | None = None,
        season: str | None = None, travel_type: str | None = None,
    ) -> list[EvidenceItem]:
        category = category or classify_search_intent(query)
        category = {"restaurant": "food"}.get(category, category)
        category = next(
            (value for term, value in {
                "新闻": "travel_updates", "资讯": "travel_updates", "活动": "notices_events", "节假日": "notices_events",
                "开放": "notices_events", "开园": "notices_events", "攻略": "trip_plans", "行程": "trip_plans",
                "交通动态": "travel_updates",
                "交通": "transportation",
            }.items() if term in query),
            category,
        )
        if category == "general":
            category = None
        # The agent historically emits leaf intents (attraction/hotel/food).
        # Metadata now stores the parent in category and the leaf in
        # sub_category, so translate transparently at the tool boundary.
        leaf = sub_category or category
        aliases = {
            "attraction": "destination_info", "city_intro": "destination_info", "culture_history": "destination_info",
            "one_day": "trip_plans", "three_day": "trip_plans", "family_trip": "trip_plans", "self_drive": "trip_plans",
            "travel_guide": "trip_plans", "hotel": "accommodation", "lodging_experience": "accommodation",
            "avoid_pitfalls": "practical_tips", "budget": "practical_tips", "faq": "practical_tips", "photography": "practical_tips",
            "opening": "notices_events", "festival": "notices_events", "traffic_update": "travel_updates", "news": "travel_updates",
        }
        leaf = aliases.get(leaf, leaf)
        parent_by_leaf = {
            "destination_info": "destination", "trip_plans": "travel_guide",
            "food": "food_lodging_transport", "accommodation": "food_lodging_transport", "transportation": "food_lodging_transport",
            "practical_tips": "travel_experience", "notices_events": "travel_news", "travel_updates": "travel_news",
        }
        if leaf in parent_by_leaf:
            category, sub_category = parent_by_leaf[leaf], leaf
        city = city if city is not None else infer_search_destination(query)
        try:
            chunks = await self.retriever.search(
                query, category=category, sub_category=sub_category, city=city,
                province=province, season=season, travel_type=travel_type,
            )
        except TypeError:
            # Keep lightweight third-party/fake retrievers compatible.
            chunks = await self.retriever.search(query)
        items = [
            EvidenceItem(
                content=chunk.content,
                title=chunk.source,
                url=chunk.source_url,
                source_type="knowledge_base",
                similarity=chunk.similarity,
                metadata=chunk.metadata,
                chunk_id=chunk.id,
            )
            for chunk in chunks
        ]
        # Metadata filters in PGVector are exact; legacy documents may have a
        # missing/incorrect city field. Apply a second destination guard to
        # prevent obvious cross-city leakage (e.g. Beijing Palace articles in
        # a Hangzhou/Xihu request) before evidence reaches the model.
        if city:
            items = [
                item for item in items
                if is_destination_compatible(
                    f"{item.title} {item.content} {item.metadata.get('city', '')}",
                    city,
                )
            ]
        return items

    def reliable(self, items: list[EvidenceItem]) -> list[EvidenceItem]:
        return [
            item
            for item in items
            if item.similarity >= self.settings.rag_similarity_threshold
        ]

    def has_knowledge_gap(self, items: list[EvidenceItem]) -> bool:
        return len(self.reliable(items)) < self.settings.rag_min_reliable_chunks
