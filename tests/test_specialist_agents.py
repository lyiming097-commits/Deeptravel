from typing import Any

import pytest

from backend.app.agent.budget_agent import BudgetEstimationAgent
from backend.app.agent.poi_agent import PoiDiscoveryAgent
from backend.app.agent.route_agent import RoutePlanningAgent
from backend.app.agent.travel_plan_agent import TravelPlanningAgent
from backend.app.config import Settings
from backend.app.llm.deepseek import DeepSeekClient
from backend.app.tools import (
    AmapMcpTool,
    EvidenceItem,
    SemanticSearchResult,
    SemanticWebSearchTool,
)


class FakeAmap:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.media_enrichment_calls = 0

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        self.calls.append((name, arguments))
        if name == "poi_search":
            return [
                {"name": "宽窄巷子", "source": "高德 MCP"},
                {"name": "武侯祠", "source": "高德 MCP"},
            ]
        if name == "weather_query":
            return {"condition": "多云", "temperature": "20-28℃"}
        if name.startswith("route_"):
            modes = {
                "route_transit": "公交/地铁",
                "route_driving": "驾车",
                "route_walking": "步行",
            }
            return {
                "origin": arguments["origin"],
                "destination": arguments["destination"],
                "mode": modes[name],
                "duration_minutes": 25,
                "distance_km": 3.0,
            }
        if name == "distance_measure":
            return {"distance_km": 3.0, "driving_duration_minutes": 20}
        raise AssertionError(f"未预期的工具：{name}")

    async def enrich_poi_media(
        self,
        places: list[dict[str, Any]],
        keywords: str = "",
        city: str = "",
    ) -> list[dict[str, Any]]:
        self.media_enrichment_calls += 1
        return places


class FakeRagTool:
    name = "rag_search"

    def __init__(self, rag_items: list[EvidenceItem] | None = None) -> None:
        self.rag_items = rag_items or []

    async def search(self, query: str) -> list[EvidenceItem]:
        return self.rag_items

    @staticmethod
    def reliable(items: list[EvidenceItem]) -> list[EvidenceItem]:
        return [item for item in items if item.similarity >= 0.5]

    def has_knowledge_gap(self, items: list[EvidenceItem]) -> bool:
        return len(self.reliable(items)) < 2


class FakeSemanticWebTool:
    tool_names = ("web_search", "web_fetch", "semantic_rerank")

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.web_items = [
            EvidenceItem(
                content="宽窄巷子适合慢速步行游览。",
                title="成都旅游资料",
                url="https://example.com/chengdu",
                source_type="external_web",
                similarity=0.88,
            )
        ]

    async def search(self, query: str, **kwargs: Any) -> SemanticSearchResult:
        self.calls.append((query, kwargs))
        return SemanticSearchResult(
            self.web_items,
            ["web_search", "web_fetch", "semantic_rerank"],
        )


class MixedCategorySemanticWebTool(FakeSemanticWebTool):
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.query = ""
        self.web_items = [
            EvidenceItem(
                content="住宿介绍",
                title="成都景区附近酒店推荐",
                url="https://example.com/hotels/chengdu",
                source_type="external_web",
                similarity=0.97,
            ),
            EvidenceItem(
                content="餐饮介绍",
                title="成都热门餐厅榜",
                url="https://example.com/restaurants/chengdu",
                source_type="external_web",
                similarity=0.95,
            ),
            EvidenceItem(
                content="成都博物馆与历史古迹介绍",
                title="成都博物馆与景点指南",
                url="https://example.com/attractions/chengdu",
                source_type="external_web",
                similarity=0.89,
            ),
        ]

    async def search(self, query: str, **kwargs: Any) -> SemanticSearchResult:
        self.query = query
        return await super().search(query, **kwargs)


def dependencies() -> tuple[Settings, DeepSeekClient, AmapMcpTool]:
    settings = Settings(
        _env_file=None,
        mock_llm=True,
        mock_amap=False,
        mock_search=True,
        embedding_dimensions=64,
        rag_similarity_threshold=0.5,
    )
    llm = DeepSeekClient("", "https://api.deepseek.com", "deepseek-chat")
    return settings, llm, AmapMcpTool(FakeAmap())


@pytest.mark.asyncio
async def test_travel_plan_agent_uses_plan_and_execute_graph() -> None:
    settings, llm, amap = dependencies()
    agent = TravelPlanningAgent(
        settings=settings,
        llm=llm,
        rag_tool=FakeRagTool(),
        web_tool=FakeSemanticWebTool(),
        amap_tool=amap,
    )

    outcome = await agent.run(
        "帮我规划成都三日游",
        {"destination": "成都", "days": 3, "people": 2, "daily_budget": 600},
    )

    assert outcome.agent_name == "travel-planning-agent"
    assert outcome.reasoning_mode == "plan-and-execute"
    assert "budget" not in outcome.result
    assert "budget_calculator" not in outcome.tools_used
    assert len(outcome.result["days_plan"]) == 3
    assert outcome.execution_trace[0]["phase"] == "plan"
    poi_calls = [arguments for name, arguments in amap.provider.calls if name == "poi_search"]
    assert poi_calls
    # Bulk itinerary searches defer detail/media fan-out. Optional landmark
    # resolution after answer composition uses limit=8 and has its own budget.
    bulk_calls = [arguments for arguments in poi_calls if arguments["limit"] != 8]
    assert bulk_calls
    assert all(arguments["enrich_details"] is False for arguments in bulk_calls)
    assert amap.provider.media_enrichment_calls == 1


@pytest.mark.asyncio
async def test_poi_agent_accepts_destination_not_in_common_city_list() -> None:
    settings, llm, amap = dependencies()
    web_tool = FakeSemanticWebTool()
    web_tool.web_items = [
        EvidenceItem(
            content="洛阳龙门石窟是当地重要旅游景点。",
            title="洛阳景点指南",
            url="https://example.com/luoyang",
            source_type="external_web",
            similarity=0.88,
        )
    ]
    agent = PoiDiscoveryAgent(
        settings=settings,
        llm=llm,
        rag_tool=FakeRagTool([]),
        web_tool=web_tool,
        amap_tool=amap,
    )

    outcome = await agent.run("洛阳的景点", {})

    assert outcome.result["destination"] == "洛阳"
    assert "web_search" in outcome.tools_used
    assert any(item[1].get("destination") == "洛阳" for item in web_tool.calls)
    assert any(citation["type"] == "external_web" for citation in outcome.citations)


@pytest.mark.asyncio
async def test_travel_plan_only_needs_destination_and_days() -> None:
    settings, llm, amap = dependencies()
    agent = TravelPlanningAgent(
        settings=settings,
        llm=llm,
        rag_tool=FakeRagTool(
            [
                EvidenceItem(
                    content="郑州二日游景点资料",
                    title="郑州旅行资料",
                    url="https://example.com/zhengzhou",
                    source_type="knowledge",
                    similarity=0.9,
                ),
                EvidenceItem(
                    content="郑州城市游览建议",
                    title="郑州攻略",
                    url="https://example.com/zhengzhou-guide",
                    source_type="knowledge",
                    similarity=0.85,
                ),
            ]
        ),
        web_tool=FakeSemanticWebTool(),
        amap_tool=amap,
    )

    outcome = await agent.run("想去郑州玩两天", {})

    assert outcome.result["days"] == 2
    assert len(outcome.result["days_plan"]) == 2
    assert "budget" not in outcome.result
    assert "budget_calculator" not in outcome.tools_used


def test_travel_plan_exposes_grounded_map_points() -> None:
    days = [{"day": 1, "activities": ["西湖", "灵隐寺"]}]
    places = [
        {"name": "西湖", "location": "120.15,30.25", "photo": "https://img.example/x.jpg"},
        {"name": "灵隐寺", "location": "120.10,30.24"},
        {"name": "无坐标地点", "photo": "https://img.example/y.jpg"},
    ]

    points = TravelPlanningAgent._map_points(places, days)

    assert points == [
        {"name": "西湖", "location": "120.15,30.25", "address": "", "day": 1, "photo": "https://img.example/x.jpg"},
        {"name": "灵隐寺", "location": "120.10,30.24", "address": "", "day": 1},
    ]


def test_travel_plan_balances_unique_pois_without_repeating_across_days() -> None:
    places = [
        {"name": "故宫"},
        {"name": "天坛公园"},
        {"name": "颐和园"},
        {"name": "圆明园"},
        {"name": "故宫"},
    ]

    days = TravelPlanningAgent._days(places, 3)
    activities = [name for day in days for name in day["activities"]]

    assert [len(day["activities"]) for day in days] == [2, 1, 1]
    assert activities == ["故宫", "天坛公园", "颐和园", "圆明园"]
    assert len(activities) == len(set(activities))


def test_travel_plan_extracts_landmarks_for_focused_poi_search() -> None:
    assert TravelPlanningAgent._extract_landmarks(
        "杭州西湖两日游，重点游览西湖和灵隐寺"
    ) == ["西湖", "灵隐寺"]


def test_travel_plan_extracts_additional_landmarks_from_composed_answer() -> None:
    answer = """
    **上午：天一阁博物馆**（适合了解宁波藏书文化）。
    **下午：月湖公园**，**晚上：鼓楼街区**。
    """

    assert TravelPlanningAgent._extract_answer_landmarks(answer) == [
        "天一阁博物馆",
        "月湖公园",
        "鼓楼街区",
    ]


def test_travel_plan_extracts_landmarks_from_plain_descriptions() -> None:
    answer = "西湖适合在傍晚慢慢游览，灵隐寺适合清晨参观。"

    assert TravelPlanningAgent._extract_answer_landmarks(answer) == ["西湖", "灵隐寺"]


def test_travel_plan_extracts_structured_landmarks_without_description_fragments() -> None:
    answer = (
        "Day 1（9月3日）：故宫博物院 → 天坛公园\n"
        "上午：故宫博物院（建议游览3小时）\n"
        "故宫位于景山前街，是明清两代的皇家宫殿。\n"
        "下午：天坛公园（建议游览2小时）\n"
        "天坛位于天坛东里，以祈年殿最为著名。"
    )

    assert TravelPlanningAgent._extract_answer_landmarks(answer) == [
        "故宫博物院",
        "天坛公园",
    ]


def test_travel_plan_rejects_theme_headings_as_landmark_entities() -> None:
    answer = (
        "**从太湖山水到古镇历史**\n"
        "无锡的景点类型很丰富，我按偏好帮你梳理。\n"
        "**古镇历史**\n"
        "适合喜欢慢节奏水乡游的人。\n"
        "**湿地公园·长广溪国家湿地公园**\n"
        "**紧邻太湖**\n"
        "**湖光山色**"
    )

    assert TravelPlanningAgent._extract_answer_landmarks(answer) == [
        "长广溪国家湿地公园"
    ]


def test_travel_plan_attaches_distinct_attraction_copy_and_rejects_route_text() -> None:
    places = [
        {"name": "西湖", "type": "风景名胜"},
        {"name": "灵隐寺", "type": "风景名胜"},
    ]
    evidence = [
        EvidenceItem(
            content=(
                "西湖以湖光山色和苏堤春晓闻名，适合清晨或傍晚漫步。"
                "从西湖到灵隐寺可乘坐公交，约 30 分钟。"
                "灵隐寺始建于东晋，是杭州著名的佛教古刹。"
            ),
            title="杭州景点资料",
            url=None,
            source_type="knowledge",
            similarity=0.9,
        )
    ]

    enriched = TravelPlanningAgent._attach_poi_descriptions(places, evidence)

    assert "湖光山色" in enriched[0]["description"]
    assert "灵隐寺始建" in enriched[1]["description"]
    assert "公交" not in enriched[1]["description"]


def test_travel_plan_replaces_duplicate_or_mixed_route_descriptions() -> None:
    places = [
        {"name": "西湖", "description": "从西湖到灵隐寺，沿途景色优美，乘坐公交约30分钟。"},
        {"name": "灵隐寺", "description": "从西湖到灵隐寺，沿途景色优美，乘坐公交约30分钟。"},
    ]
    evidence = [
        EvidenceItem(
            content=(
                "西湖以湖光山色闻名，是杭州最具代表性的自然景观。"
                "灵隐寺始建于东晋，保存有丰富的佛教历史遗迹。"
            ),
            title="杭州景点资料",
            url=None,
            source_type="knowledge",
            similarity=0.9,
        )
    ]

    enriched = TravelPlanningAgent._attach_poi_descriptions(places, evidence)

    assert "公交" not in enriched[0]["description"]
    assert "公交" not in enriched[1]["description"]
    assert enriched[0]["description"] != enriched[1]["description"]
    assert "湖光山色" in enriched[0]["description"]
    assert "始建于东晋" in enriched[1]["description"]


def test_travel_plan_drops_unusable_route_description_without_evidence() -> None:
    places = [{"name": "西湖", "description": "从西湖到灵隐寺乘坐公交约30分钟。"}]

    enriched = TravelPlanningAgent._attach_poi_descriptions(places, [])

    assert "description" not in enriched[0]


def test_travel_plan_prioritizes_landmark_over_ticket_facilities() -> None:
    places = [
        {"name": "龙门石窟售票处"},
        {"name": "龙门石窟"},
        {"name": "龙门石窟游客中心"},
    ]
    ranked = TravelPlanningAgent._prioritize_requested_pois(places, ["龙门石窟"])
    assert [item["name"] for item in ranked] == [
        "龙门石窟",
        "龙门石窟售票处",
        "龙门石窟游客中心",
    ]


def test_travel_plan_normalises_provider_photo_shapes() -> None:
    places = [
        {
            "name": "西湖",
            "photos": [{"large_url": "https://img.example/west-lake.jpg"}],
        },
        {
            "name": "灵隐寺",
            "photo": "https://img.example/lingyin-1.jpg|https://img.example/lingyin-2.jpg",
        },
    ]

    normalized = TravelPlanningAgent._normalise_poi_media(places)

    assert normalized[0]["photo"] == "https://img.example/west-lake.jpg"
    assert normalized[0]["photos"] == ["https://img.example/west-lake.jpg"]
    assert normalized[1]["photos"] == [
        "https://img.example/lingyin-1.jpg",
        "https://img.example/lingyin-2.jpg",
    ]


def test_travel_plan_drops_supporting_facilities_from_itinerary() -> None:
    places = [
        {"name": "宁波天一阁"},
        {"name": "天一阁游客服务中心"},
        {"name": "天一阁停车场"},
    ]

    assert [item["name"] for item in TravelPlanningAgent._remove_supporting_pois(places)] == [
        "宁波天一阁"
    ]


def test_poi_query_preserves_concrete_landmark_without_category_word() -> None:
    assert PoiDiscoveryAgent._poi_keywords("龙门石窟") == "龙门石窟"


def test_travel_plan_filters_unrelated_pois_for_explicit_landmark() -> None:
    places = [
        {"name": "天安门广场", "city": "北京"},
        {"name": "龙门石窟", "city": "洛阳"},
        {"name": "龙门石窟西山石窟", "city": "洛阳"},
    ]
    filtered = TravelPlanningAgent._filter_requested_pois(places, ["龙门石窟"])
    assert [item["name"] for item in filtered] == ["龙门石窟", "龙门石窟西山石窟"]
    assert TravelPlanningAgent._filter_requested_pois(
        [{"name": "天安门广场"}], ["龙门石窟"]
    ) == []


@pytest.mark.asyncio
async def test_travel_agent_answers_accommodation_without_requesting_days() -> None:
    settings, llm, amap = dependencies()
    agent = TravelPlanningAgent(
        settings=settings,
        llm=llm,
        rag_tool=FakeRagTool(),
        web_tool=FakeSemanticWebTool(),
        amap_tool=amap,
    )

    outcome = await agent.run("杭州西湖附近酒店", {})

    assert outcome.result["intent"] == "accommodation"
    assert outcome.result["needs_clarification"] is False
    assert outcome.result["query_type"] == "accommodation"
    assert "poi_search" in outcome.tools_used
    assert "天数" not in outcome.answer


@pytest.mark.asyncio
async def test_travel_plan_uses_dynamic_area_entity_for_accommodation() -> None:
    settings, llm, amap = dependencies()
    web_tool = FakeSemanticWebTool()
    agent = TravelPlanningAgent(
        settings=settings,
        llm=llm,
        rag_tool=FakeRagTool(),
        web_tool=web_tool,
        amap_tool=amap,
    )

    outcome = await agent.run("杭州西溪湿地附近酒店", {})

    assert outcome.result["area"] == "西溪湿地"
    assert outcome.result["query_type"] == "accommodation"
    assert any("西溪湿地" in call[0] for call in web_tool.calls)


@pytest.mark.asyncio
async def test_travel_plan_supports_food_recommendation_without_days() -> None:
    settings, llm, amap = dependencies()
    web_tool = FakeSemanticWebTool()
    agent = TravelPlanningAgent(
        settings=settings,
        llm=llm,
        rag_tool=FakeRagTool(),
        web_tool=web_tool,
        amap_tool=amap,
    )

    outcome = await agent.run("洛阳有什么特色美食", {})

    assert outcome.result["travel_intent"] == "food"
    assert outcome.result["query_type"] == "poi_recommendation"
    assert "天数" not in outcome.result["missing"]


@pytest.mark.asyncio
async def test_poi_react_agent_falls_back_from_rag_to_mcp_and_web() -> None:
    settings, llm, amap = dependencies()
    agent = PoiDiscoveryAgent(
        settings=settings,
        llm=llm,
        rag_tool=FakeRagTool([]),
        web_tool=FakeSemanticWebTool(),
        amap_tool=amap,
    )

    outcome = await agent.run("成都有哪些适合慢游的景点？", {"destination": "成都"})

    assert outcome.reasoning_mode == "react"
    assert outcome.tools_used == [
        "rag_search",
        "poi_search",
        "web_search",
        "web_fetch",
        "semantic_rerank",
    ]
    assert outcome.result["query_type"] == "poi_discovery"
    assert outcome.result["pois"][0]["name"] == "宽窄巷子"
    assert outcome.citations[0]["type"] == "map_mcp"
    assert outcome.citations[1]["type"] == "external_web"


@pytest.mark.asyncio
async def test_poi_agent_reserves_last_tool_call_for_live_web_search() -> None:
    settings, llm, amap = dependencies()
    settings.agent_max_tool_calls = 1
    agent = PoiDiscoveryAgent(
        settings=settings,
        llm=llm,
        rag_tool=FakeRagTool(),
        web_tool=FakeSemanticWebTool(),
        amap_tool=amap,
    )

    outcome = await agent.run("成都的景点", {})

    assert outcome.tools_used == ["web_search", "web_fetch", "semantic_rerank"]
    assert outcome.execution_trace[0]["phase"] == "action"


@pytest.mark.asyncio
async def test_poi_attraction_query_excludes_hotel_and_restaurant_links() -> None:
    settings, llm, amap = dependencies()
    web_tool = MixedCategorySemanticWebTool()
    agent = PoiDiscoveryAgent(
        settings=settings,
        llm=llm,
        rag_tool=FakeRagTool([]),
        web_tool=web_tool,
        amap_tool=amap,
    )

    outcome = await agent.run("成都有哪些值得去的景点？", {"destination": "成都"})

    external_urls = [
        citation["url"]
        for citation in outcome.citations
        if citation["type"] == "external_web"
    ]
    assert outcome.result["intent"] == "attraction"
    assert external_urls == ["https://example.com/attractions/chengdu"]
    assert "景区" in web_tool.query
    assert "博物馆" in web_tool.query


@pytest.mark.asyncio
async def test_route_react_agent_honours_explicit_driving_mode() -> None:
    settings, llm, amap = dependencies()
    agent = RoutePlanningAgent(settings=settings, llm=llm, amap_tool=amap)

    outcome = await agent.run(
        "帮我规划路线",
        {
            "origin": "宽窄巷子",
            "destination": "武侯祠",
            "city": "成都",
            "mode": "driving",
        },
    )

    assert outcome.tools_used == ["route_driving", "distance_measure"]
    assert outcome.result["mode"] == "驾车"


@pytest.mark.asyncio
async def test_route_react_agent_maps_high_speed_rail_to_transit() -> None:
    settings, llm, amap = dependencies()
    agent = RoutePlanningAgent(settings=settings, llm=llm, amap_tool=amap)

    outcome = await agent.run("郑州到杭州，想坐高铁", {})

    assert outcome.tools_used == ["route_transit", "distance_measure"]
    assert outcome.result["mode"] == "公交/地铁"
    assert outcome.result["transport_preference"] == "high_speed_rail"
    assert outcome.result["preference_matched"] is False
    assert "没有返回 G 字头高铁" in outcome.answer


@pytest.mark.asyncio
async def test_route_agent_passes_live_web_evidence_to_answer_model() -> None:
    settings, llm, amap = dependencies()
    web_tool = FakeSemanticWebTool()
    agent = RoutePlanningAgent(
        settings=settings,
        llm=llm,
        amap_tool=amap,
        web_tool=web_tool,
    )

    outcome = await agent.run("郑州到杭州", {})

    assert "semantic_rerank" in outcome.tools_used
    assert any(citation["type"] == "external_web" for citation in outcome.citations)


def test_route_agent_extracts_natural_language_endpoints() -> None:
    parsed = RoutePlanningAgent.extract_parameters("从成都宽窄巷子到武侯祠，想坐公交")

    assert parsed["origin"] == "成都宽窄巷子"
    assert parsed["destination"] == "武侯祠"
    assert parsed["city"] == "成都"
    assert parsed["mode"] == "transit"


@pytest.mark.parametrize(
    "message",
    ["郑州到杭州", "帮我规划郑州去杭州", "郑州前往杭州"],
)
def test_route_agent_extracts_bare_cross_city_requests(message: str) -> None:
    parsed = RoutePlanningAgent.extract_parameters(message)

    assert parsed["origin"] == "郑州"
    assert parsed["destination"] == "杭州"
    # A cross-city request must not apply one city as a global geocoding limit.
    assert not parsed.get("city")


def test_route_agent_prefers_latest_route_in_short_memory() -> None:
    parsed = RoutePlanningAgent.extract_parameters("之前从北京到上海\n现在郑州到杭州")

    assert parsed["origin"] == "郑州"
    assert parsed["destination"] == "杭州"


@pytest.mark.asyncio
async def test_route_agent_passes_cross_city_endpoints_without_city_limit() -> None:
    settings, llm, amap = dependencies()
    agent = RoutePlanningAgent(settings=settings, llm=llm, amap_tool=amap)

    outcome = await agent.run("郑州到杭州", {})

    assert outcome.result["origin"] == "郑州"
    assert outcome.result["destination"] == "杭州"
    route_call = next(call for call in amap.provider.calls if call[0] == "route_driving")
    assert route_call[1]["city"] == ""


@pytest.mark.asyncio
async def test_budget_agent_reflects_and_keeps_arithmetic_consistent() -> None:
    settings, llm, _ = dependencies()
    agent = BudgetEstimationAgent(settings=settings, llm=llm)

    outcome = await agent.run(
        "估算三天两人预算",
        {"days": 3, "people": 2, "daily_budget": 500},
    )

    assert outcome.reasoning_mode == "reflection"
    assert outcome.result["estimated_total"] == 3000
    assert sum(outcome.result["breakdown"].values()) == 3000
    assert outcome.result["review"]["valid"] is True


@pytest.mark.asyncio
async def test_budget_agent_passes_live_web_evidence_to_answer_model() -> None:
    settings, llm, _ = dependencies()
    web_tool = FakeSemanticWebTool()
    agent = BudgetEstimationAgent(settings=settings, llm=llm, web_tool=web_tool)

    outcome = await agent.run(
        "估算三天两人预算",
        {"days": 3, "people": 2, "daily_budget": 500},
    )

    assert "web_fetch" in outcome.tools_used
    assert any(citation["type"] == "external_web" for citation in outcome.citations)


def test_budget_agent_extracts_chinese_natural_language_numbers() -> None:
    parsed = BudgetEstimationAgent.extract_parameters(
        "两个成年人去成都玩五天，每人每天预算 600 元"
    )

    assert parsed == {"days": 5, "people": 2, "daily_budget": 600.0}


def test_budget_agent_extracts_total_budget() -> None:
    parsed = BudgetEstimationAgent.extract_parameters("成都四天两人，总预算 5000 元")

    assert parsed == {"days": 4, "people": 2, "total_budget": 5000.0}


class FakeEmbedding:
    async def embed_query(self, text: str) -> list[float]:
        return [1.0, 0.0]

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] if "成都" in text else [0.0, 1.0] for text in texts]


class FakeWebTool:
    def __init__(self) -> None:
        self.calls = 0

    async def search_and_fetch(self, query: str, max_results: int = 5) -> list[dict[str, Any]]:
        self.calls += 1
        return [
            {
                "title": "无关页面",
                "url": "https://example.com/other",
                "content": "数据库索引维护。",
            },
            {
                "title": "成都攻略",
                "url": "https://example.com/chengdu",
                "content": "成都宽窄巷子适合慢游。",
            },
        ]


@pytest.mark.asyncio
async def test_semantic_web_tool_reranks_fetched_content() -> None:
    settings, _, _ = dependencies()
    page_source = FakeWebTool()
    tool = SemanticWebSearchTool(
        settings,
        embedding=FakeEmbedding(),
        page_source=page_source,
    )

    result = await tool.search("成都慢游")

    assert page_source.calls == 1
    assert result.items[0].title == "成都攻略"
    assert result.tools_used == ["web_search", "web_fetch", "semantic_rerank"]


class UnavailableEmbedding:
    async def embed_query(self, text: str) -> list[float]:
        raise RuntimeError("Ollama unavailable")


@pytest.mark.asyncio
async def test_semantic_web_tool_attempts_live_search_before_embedding() -> None:
    settings, _, _ = dependencies()
    page_source = FakeWebTool()
    tool = SemanticWebSearchTool(
        settings,
        embedding=UnavailableEmbedding(),
        page_source=page_source,
    )

    result = await tool.search("洛阳的景点", destination="洛阳")

    assert page_source.calls == 1
    assert result.items == []
    assert result.tools_used == ["web_search", "web_fetch", "semantic_rerank"]
