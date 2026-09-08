"""Agent 可调用的外部能力工具层。"""

from backend.app.tools.amap import AmapMcpTool
from backend.app.tools.itinerary_map import ItineraryMapTool
from backend.app.tools.models import EvidenceItem, SemanticSearchResult
from backend.app.tools.poi_media import PoiMediaTool
from backend.app.tools.rag import RagSearchTool
from backend.app.tools.railway import RailwayMcpTool
from backend.app.tools.registry import AgentToolRegistry
from backend.app.tools.relevance import (
    SearchIntent,
    build_search_query,
    classify_search_intent,
    deduplicate_poi_items,
    extract_landmark_terms,
    filter_evidence_items,
    filter_poi_items,
    filter_pois_by_landmarks,
    infer_search_destination,
    is_probably_descriptive_poi_name,
)
from backend.app.tools.web import BrowserSearchTool, SemanticWebSearchTool

__all__ = [
    "AgentToolRegistry",
    "AmapMcpTool",
    "BrowserSearchTool",
    "EvidenceItem",
    "ItineraryMapTool",
    "PoiMediaTool",
    "RagSearchTool",
    "RailwayMcpTool",
    "SearchIntent",
    "SemanticSearchResult",
    "SemanticWebSearchTool",
    "build_search_query",
    "classify_search_intent",
    "deduplicate_poi_items",
    "extract_landmark_terms",
    "filter_evidence_items",
    "filter_poi_items",
    "filter_pois_by_landmarks",
    "infer_search_destination",
    "is_probably_descriptive_poi_name",
]
