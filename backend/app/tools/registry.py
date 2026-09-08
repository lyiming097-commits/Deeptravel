from dataclasses import dataclass

from backend.app.config import Settings
from backend.app.maps import AmapMcpProvider, MockMapProvider
from backend.app.mcp.client import McpClient
from backend.app.rag.embedding import build_embedding_provider
from backend.app.rag.retriever import RagRetriever
from backend.app.railways import RailwayMcpProvider
from backend.app.repositories import save_web_candidates
from backend.app.tools.amap import AmapMcpTool
from backend.app.tools.itinerary_map import ItineraryMapTool
from backend.app.tools.poi_media import PoiMediaTool
from backend.app.tools.rag import RagSearchTool
from backend.app.tools.railway import RailwayMcpTool
from backend.app.tools.web import BrowserSearchTool, SemanticWebSearchTool


@dataclass(frozen=True)
class AgentToolRegistry:
    """在组合根中构建并向 Agent 注入所有工具。"""

    rag: RagSearchTool
    amap: AmapMcpTool
    railway: RailwayMcpTool
    web: SemanticWebSearchTool
    itinerary_map: ItineraryMapTool
    poi_media: PoiMediaTool

    @classmethod
    def from_settings(cls, settings: Settings) -> "AgentToolRegistry":
        embedding = build_embedding_provider(settings)
        rag = RagSearchTool(
            settings,
            RagRetriever(settings, embedding=embedding),
        )
        browser = BrowserSearchTool(
            McpClient(
                settings.search_mcp_endpoint,
                settings.search_mcp_internal_api_key,
                auth_header="X-Search-Key",
                timeout=15,
            ),
            settings.web_fetch_max_pages,
        )
        web = SemanticWebSearchTool(
            settings,
            embedding,
            browser,
            candidate_sink=save_web_candidates,
        )
        map_provider = (
            MockMapProvider()
            if settings.amap_mocked
            else AmapMcpProvider(
                settings.amap_mcp_endpoint,
                settings.amap_mcp_api_key,
                settings.amap_mcp_timeout_seconds,
            )
        )
        railway = RailwayMcpTool(
            RailwayMcpProvider(
                settings.railway_mcp_endpoint,
                settings.railway_mcp_timeout_seconds,
            )
        )
        amap = AmapMcpTool(map_provider)
        itinerary_map = ItineraryMapTool()
        return cls(
            rag=rag,
            amap=amap,
            railway=railway,
            web=web,
            itinerary_map=itinerary_map,
            poi_media=PoiMediaTool(amap, itinerary_map),
        )
