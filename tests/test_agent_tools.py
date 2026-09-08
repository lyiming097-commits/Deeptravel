from types import SimpleNamespace
from typing import Any

import pytest

from backend.app.config import Settings
from backend.app.tools import (
    AmapMcpTool,
    BrowserSearchTool,
    EvidenceItem,
    ItineraryMapTool,
    PoiMediaTool,
    RagSearchTool,
    SemanticWebSearchTool,
    classify_search_intent,
    deduplicate_poi_items,
    filter_evidence_items,
    filter_poi_items,
)


def test_itinerary_map_tool_builds_only_verified_points() -> None:
    tool = ItineraryMapTool()
    points = tool.build_points(
        [
            {"name": "西湖", "location": "120.10,30.25", "photo": "https://img.example/x.jpg"},
            {"name": "错误坐标", "location": "200,95"},
        ],
        [{"day": 1, "activities": ["西湖"]}],
    )

    assert points == [
        {
            "name": "西湖",
            "location": "120.10,30.25",
            "address": "",
            "day": 1,
            "photo": "https://img.example/x.jpg",
        }
    ]


def test_attraction_filter_rejects_businesses_residences_and_closed_places() -> None:
    pois = [
        {
            "name": "北京越野(北京祥龙博瑞店)",
            "type": "010400",
            "typecode": "010400",
            "address": "安宁庄东路15号博瑞汽车园区",
            "city": "北京",
        },
        {
            "name": "城市广场",
            "type": "商务住宅;住宅区;住宅小区",
            "typecode": "120302",
            "address": "十里堡甲3号院",
            "city": "北京",
        },
        {
            "name": "北京天文馆(暂停开放)",
            "type": "140700",
            "typecode": "140700",
            "address": "西直门外大街138号",
            "city": "北京",
        },
        {
            "name": "天安门广场",
            "type": "风景名胜;公园广场;城市广场",
            "typecode": "110210|110105",
            "address": "东长安街",
            "city": "北京",
        },
        {
            "name": "中国国家博物馆",
            "type": "科教文化服务;博物馆",
            "typecode": "140100",
            "address": "东长安街16号",
            "city": "北京",
        },
    ]

    filtered = filter_poi_items(pois, "attraction", "北京")

    assert [item["name"] for item in filtered] == ["天安门广场", "中国国家博物馆"]


def test_itinerary_filter_removes_route_activity_products_but_keeps_sights() -> None:
    pois = [
        {"name": "西湖经典环线", "type": "风景名胜", "typecode": "110000", "city": "杭州"},
        {"name": "河坊街夜游", "type": "风景名胜", "typecode": "110000", "city": "杭州"},
        {
            "name": "杭州西湖风景名胜区-白堤-石拱桥与湖面游船(打卡点)",
            "type": "风景名胜",
            "typecode": "110000",
            "city": "杭州",
        },
        {"name": "西湖", "type": "风景名胜", "typecode": "110000", "city": "杭州"},
        {"name": "灵隐寺", "type": "风景名胜", "typecode": "110000", "city": "杭州"},
    ]

    itinerary = filter_poi_items(
        pois, "attraction", "杭州", for_itinerary=True
    )
    direct_search = filter_poi_items(pois, "attraction", "杭州")

    assert [item["name"] for item in itinerary] == ["西湖", "灵隐寺"]
    assert "河坊街夜游" in [item["name"] for item in direct_search]


def test_attraction_filter_rejects_descriptive_answer_fragments() -> None:
    pois = [
        {"name": "从太湖山水", "type": "风景名胜", "typecode": "110000", "city": "无锡"},
        {"name": "古镇历史", "type": "风景名胜", "typecode": "110000", "city": "无锡"},
        {"name": "紧邻太湖", "type": "风景名胜", "typecode": "110000", "city": "无锡"},
        {"name": "湖光山色", "type": "风景名胜", "typecode": "110000", "city": "无锡"},
        {"name": "长广溪国家湿地公园", "type": "风景名胜", "typecode": "110000", "city": "无锡"},
    ]

    assert [item["name"] for item in filter_poi_items(pois, "attraction", "无锡")] == [
        "长广溪国家湿地公园"
    ]


def test_poi_media_tool_builds_concise_display_name_without_changing_identity() -> None:
    item = {
        "name": "杭州西湖风景名胜区-白堤-入口",
        "city": "杭州市",
    }

    assert PoiMediaTool.poi_display_name(item) == "西湖风景名胜区"
    assert item["name"] == "杭州西湖风景名胜区-白堤-入口"

    assert PoiMediaTool.poi_display_name(
        {"name": "湿地公园·长广溪国家湿地公园", "city": "无锡"}
    ) == "长广溪国家湿地公园"


def test_poi_deduplication_prefers_main_landmark_over_internal_points() -> None:
    pois = [
        {"name": "故宫博物院-午门", "rating": "4.9"},
        {"name": "故宫博物院", "rating": "4.8"},
        {"name": "天安门广场-国旗"},
        {"name": "天安门广场"},
        {"name": "天坛公园"},
    ]

    deduplicated = deduplicate_poi_items(pois)

    assert [item["name"] for item in deduplicated] == [
        "故宫博物院",
        "天安门广场",
        "天坛公园",
    ]


def test_poi_media_tool_normalises_images_without_agent_dependency() -> None:
    normalized = PoiMediaTool.normalise_poi_media(
        [
            {
                "name": "西湖",
                "photos": [
                    {"large_url": "https://img.example/west-lake.jpg"},
                    "https://img.example/west-lake-2.jpg",
                    "https://img.example/extra.jpg",
                ],
            }
        ]
    )

    assert normalized == [
        {
            "name": "西湖",
            "photo": "https://img.example/west-lake.jpg",
            "photos": [
                "https://img.example/west-lake.jpg",
                "https://img.example/west-lake-2.jpg",
            ],
        }
    ]


def test_poi_media_tool_does_not_use_schedule_addresses_as_street_intros() -> None:
    evidence = [
        EvidenceItem(
            content=(
                "景点简介 下午把时间留给中国科举博物馆（贡院街95号）。"
                "中午步行到南京夫子庙（贡院街152号）。"
                "贡院街是夫子庙秦淮风光带的重要历史街区，沿街保留了传统市井风貌。"
            ),
            title="南京游览安排",
            url=None,
            source_type="external_web",
            similarity=0.9,
        )
    ]

    enriched = PoiMediaTool.attach_poi_descriptions([{"name": "贡院街"}], evidence)

    assert "历史街区" in enriched[0]["description"]
    assert "下午" not in enriched[0]["description"]
    assert "步行到" not in enriched[0]["description"]


def test_poi_media_tool_keeps_short_grounded_intros_and_rejects_generic_copy() -> None:
    evidence = [
        EvidenceItem(
            content="灵隐寺始建于东晋，是杭州著名古刹。",
            title="杭州景点资料",
            url=None,
            source_type="knowledge_base",
            similarity=0.9,
        )
    ]
    enriched = PoiMediaTool.attach_poi_descriptions(
        [
            {"name": "灵隐寺", "description": "这里风景优美，适合游览。"},
        ],
        evidence,
    )
    assert enriched[0]["description"] == "灵隐寺始建于东晋，是杭州著名古刹。"


def test_poi_media_tool_maps_labelled_answer_lines_to_matching_pois() -> None:
    places = [{"name": "西湖"}, {"name": "灵隐寺"}]
    answer = (
        "西湖\n杭州的标志性景点，以湖光山色闻名，适合漫步。\n"
        "灵隐寺：始建于东晋，是杭州著名古刹。"
    )
    enriched = PoiMediaTool.attach_answer_descriptions(places, answer)
    assert "湖光山色" in enriched[0]["description"]
    assert "始建于东晋" in enriched[1]["description"]


def test_poi_media_tool_matches_model_intro_to_clean_display_name() -> None:
    places = [{"name": "古华公园-圆梦博物馆", "city": "上海"}]
    answer = "古华公园：园内绿地与文化场馆相结合，适合亲子休闲和短时游览。"

    enriched = PoiMediaTool.attach_answer_descriptions(places, answer)

    assert "文化场馆" in enriched[0]["description"]


def test_poi_media_tool_does_not_copy_one_mixed_intro_to_two_pois() -> None:
    evidence = [
        EvidenceItem(
            content="西湖、灵隐寺都是杭州热门景点，适合游览。",
            title="杭州景点资料",
            url=None,
            source_type="knowledge_base",
            similarity=0.9,
        )
    ]
    enriched = PoiMediaTool.attach_poi_descriptions(
        [{"name": "西湖"}, {"name": "灵隐寺"}], evidence
    )
    assert "description" not in enriched[0]
    assert "description" not in enriched[1]


def test_poi_media_tool_attaches_only_name_matched_web_images() -> None:
    evidence = [
        EvidenceItem(
            content="洛阳龙门石窟是世界文化遗产。",
            title="洛阳龙门石窟游览指南",
            url="https://travel.example.com/luoyang",
            source_type="external_web",
            similarity=0.95,
            metadata={
                "images": [
                    {"url": "https://img.example/longmen.jpg", "alt": "龙门石窟卢舍那大佛"},
                    {"url": "https://img.example/tiananmen.jpg", "alt": "北京天安门"},
                ]
            },
        )
    ]
    enriched = PoiMediaTool.attach_evidence_images(
        [{"name": "龙门石窟"}], evidence, destination="洛阳"
    )
    assert enriched[0]["photos"] == ["https://img.example/longmen.jpg"]


def test_poi_media_tool_rejects_generic_city_page_hero_image() -> None:
    evidence = [
        EvidenceItem(
            content="宁波有天一阁、月湖等景点。",
            title="宁波景点大全",
            url="https://travel.example.com/ningbo",
            source_type="external_web",
            similarity=0.9,
            metadata={"images": [{"url": "https://img.example/generic.jpg", "alt": "旅游风光"}]},
        )
    ]
    enriched = PoiMediaTool.attach_evidence_images(
        [{"name": "天一阁"}], evidence, destination="宁波"
    )
    assert "photos" not in enriched[0]


def test_poi_media_tool_accepts_single_search_image_metadata() -> None:
    evidence = [
        EvidenceItem(
            content="龙门石窟是洛阳著名景点。",
            title="龙门石窟介绍",
            url="https://travel.example.com/longmen",
            source_type="external_web",
            similarity=0.9,
            metadata={"images": "https://img.example/longmen.jpg"},
        )
    ]
    enriched = PoiMediaTool.attach_evidence_images(
        [{"name": "龙门石窟"}], evidence, destination="洛阳"
    )
    assert enriched[0]["photo"] == "https://img.example/longmen.jpg"


def test_poi_media_tool_does_not_share_one_combined_hero_between_pois() -> None:
    evidence = [
        EvidenceItem(
            content="天一阁与月湖景区都是宁波的文化地标。",
            title="宁波天一阁·月湖景区攻略",
            url="https://travel.example.com/ningbo/tianyi-moon",
            source_type="external_web",
            similarity=0.9,
            metadata={"images": [{"url": "https://img.example/collage.jpg"}]},
        )
    ]
    enriched = PoiMediaTool.attach_evidence_images(
        [{"name": "天一阁"}, {"name": "月湖"}], evidence, destination="宁波"
    )
    assert all("photos" not in item for item in enriched)


class FakeRetriever:
    async def search(self, query: str) -> list[Any]:
        return [
            SimpleNamespace(
                id="chunk-1",
                content="宽窄巷子适合慢游。",
                source="chengdu.md",
                source_url="https://example.com/chengdu",
                similarity=0.82,
                metadata={"city": "成都"},
            ),
            SimpleNamespace(
                id="chunk-2",
                content="无关信息。",
                source="other.md",
                source_url=None,
                similarity=0.2,
                metadata={},
            ),
        ]


@pytest.mark.asyncio
async def test_rag_tool_owns_threshold_and_gap_detection() -> None:
    settings = Settings(
        _env_file=None,
        rag_similarity_threshold=0.7,
        rag_min_reliable_chunks=2,
    )
    tool = RagSearchTool(settings, FakeRetriever())

    items = await tool.search("成都慢游")

    assert [item.chunk_id for item in tool.reliable(items)] == ["chunk-1"]
    assert tool.has_knowledge_gap(items) is True


class FakeSearchClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((name, arguments))
        if name == "web_search":
            return {
                "results": [
                    {
                        "title": "成都攻略",
                        "url": "https://example.com/chengdu",
                        "snippet": "搜索摘要",
                    }
                ]
            }
        return {
            "title": "成都攻略正文",
            "final_url": arguments["url"],
            "content": "抓取后的网页正文",
            "images": [{"url": "https://img.example/chengdu.jpg", "alt": "成都景点"}],
        }


@pytest.mark.asyncio
async def test_browser_search_tool_hides_search_mcp_protocol_from_agents() -> None:
    client = FakeSearchClient()
    tool = BrowserSearchTool(client, max_pages=1)

    pages = await tool.search_and_fetch("成都攻略")

    assert [name for name, _ in client.calls] == ["web_search", "web_fetch"]
    assert pages[0]["content"] == "抓取后的网页正文"
    assert pages[0]["images"][0]["url"] == "https://img.example/chengdu.jpg"


class UnfetchableSearchClient(FakeSearchClient):
    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((name, arguments))
        if name == "web_search":
            return {
                "results": [
                    {
                        "title": "只有搜索摘要",
                        "url": "https://example.com/unavailable",
                        "snippet": "这段摘要不能冒充抓取后的网页正文。",
                    }
                ]
            }
        raise RuntimeError("网页抓取失败")


@pytest.mark.asyncio
async def test_browser_search_does_not_send_snippet_when_page_fetch_fails() -> None:
    client = UnfetchableSearchClient()
    tool = BrowserSearchTool(client, max_pages=1)

    pages = await tool.search_and_fetch("成都攻略")

    assert pages == []
    assert [name for name, _ in client.calls] == ["web_search", "web_fetch"]


class FakeMapProvider:
    source_name = "高德地图 MCP"

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        return {"tool": name, **arguments}


class LocationOnlyMapProvider:
    source_name = "高德地图 MCP"
    locations = {
        "西湖": "120.148663,30.242369",
        "灵隐寺": "120.101406,30.240238",
    }

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        if name == "poi_search":
            entity = str(arguments.get("keywords") or "")
            location = self.locations.get(entity, "")
            return [{"name": entity, "city": arguments.get("city"), "location": location}]
        return {}

    async def resolve_poi(self, entity: str, city: str = "") -> dict[str, Any]:
        location = self.locations.get(entity, "")
        return {"name": entity, "city": city, "location": location} if location else {}

    async def enrich_poi_locations(
        self, places: list[dict[str, Any]], city: str = ""
    ) -> list[dict[str, Any]]:
        return [
            {
                **item,
                "location": item.get("location") or self.locations.get(str(item.get("name") or ""), ""),
                "city": item.get("city") or city,
            }
            for item in places
        ]


class GeocodeOnlyMapProvider:
    source_name = "高德地图 MCP"

    async def resolve_poi(self, entity: str, city: str = "") -> dict[str, Any]:
        return {
            "name": entity,
            "city": city,
            "location": "120.10,30.20",
            "resolution_method": "geocode",
        }

    async def enrich_poi_locations(
        self, places: list[dict[str, Any]], city: str = ""
    ) -> list[dict[str, Any]]:
        return places


@pytest.mark.asyncio
async def test_amap_tool_exposes_typed_route_boundary() -> None:
    tool = AmapMcpTool(FakeMapProvider())

    result = await tool.route("route_walking", "宽窄巷子", "武侯祠", "成都")

    assert result["tool"] == "route_walking"
    assert result["origin"] == "宽窄巷子"
    with pytest.raises(RuntimeError, match="无效"):
        await tool.route("poi_search", "宽窄巷子", "武侯祠", "成都")


@pytest.mark.asyncio
async def test_answer_poi_coordinates_and_map_do_not_depend_on_photos() -> None:
    amap = AmapMcpTool(LocationOnlyMapProvider())
    media = PoiMediaTool(amap, ItineraryMapTool())
    result = {
        "destination": "杭州",
        "pois": [{"name": "西湖", "location": ""}],
        "days_plan": [{"day": 1, "activities": ["西湖", "灵隐寺"]}],
        "map": {"provider": "OpenStreetMap", "points": []},
    }

    enriched = await media.enrich_answer_pois(
        "Day 1：西湖 → 灵隐寺\n上午：西湖\n下午：灵隐寺",
        result,
    )

    assert all(not item.get("photo") for item in enriched["pois"])
    assert [item["name"] for item in enriched["pois"]] == ["西湖", "灵隐寺"]
    assert [point["name"] for point in enriched["map"]["points"]] == ["西湖", "灵隐寺"]
    assert all(point["location"] for point in enriched["map"]["points"])


@pytest.mark.asyncio
async def test_answer_enrichment_does_not_promote_geocode_only_text_to_poi() -> None:
    media = PoiMediaTool(AmapMcpTool(GeocodeOnlyMapProvider()), ItineraryMapTool())
    result = {
        "destination": "无锡",
        "pois": [],
        "days_plan": [],
        "map": {"provider": "OpenStreetMap", "points": []},
    }

    enriched = await media.enrich_answer_pois("上午：梦境公园", result)

    assert enriched["pois"] == []
    assert enriched["map"]["points"] == []


class FakeEmbedding:
    async def embed_query(self, text: str) -> list[float]:
        return [1.0, 0.0]

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]


def test_category_filter_keeps_only_the_requested_poi_kind() -> None:
    items = [
        EvidenceItem(
            content="酒店正文中也可能提到西湖。",
            title="杭州西湖附近酒店推荐",
            url="https://example.com/hotels/hangzhou",
            source_type="external_web",
            similarity=0.95,
        ),
        EvidenceItem(
            content="餐厅正文中也可能提到西湖。",
            title="杭州西湖边热门餐厅",
            url="https://example.com/restaurants/hangzhou",
            source_type="external_web",
            similarity=0.93,
        ),
        EvidenceItem(
            content="旅行平台的酒店预订页。",
            title="携程旅行：杭州酒店推荐",
            url="https://example.com/hotels/hangzhou-booking",
            source_type="external_web",
            similarity=0.92,
        ),
        EvidenceItem(
            content="西湖、灵隐寺与良渚古城介绍。",
            title="杭州景点与古迹指南",
            url="https://example.com/attractions/hangzhou",
            source_type="external_web",
            similarity=0.88,
        ),
    ]

    attraction_items = filter_evidence_items(items, "attraction")
    hotel_items = filter_evidence_items(items, "hotel")
    restaurant_items = filter_evidence_items(items, "restaurant")

    assert [item.title for item in attraction_items] == ["杭州景点与古迹指南"]
    assert [item.title for item in hotel_items] == [
        "杭州西湖附近酒店推荐",
        "携程旅行：杭州酒店推荐",
    ]
    assert [item.title for item in restaurant_items] == ["杭州西湖边热门餐厅"]


def test_category_intent_uses_the_latest_requested_kind() -> None:
    assert classify_search_intent("酒店附近有哪些景点") == "attraction"
    assert classify_search_intent("景点旁边住什么酒店") == "hotel"


class AttractionLiveSearch:
    def __init__(self) -> None:
        self.calls = 0

    async def search_and_fetch(self, *args, **kwargs) -> list[dict[str, Any]]:
        self.calls += 1
        return [
            {
                "title": "杭州博物馆与景点指南",
                "url": "https://example.com/attractions/hangzhou",
                "snippet": "杭州值得参观的博物馆和景点",
                "content": "杭州博物馆、西湖和良渚古城都是当地旅游景点。",
                "images": [{"url": "https://img.example/west-lake.jpg", "alt": "西湖"}],
            }
        ]


@pytest.mark.asyncio
async def test_web_search_is_transient_and_returns_live_ranked_evidence() -> None:
    settings = Settings(_env_file=None)
    source = AttractionLiveSearch()
    tool = SemanticWebSearchTool(settings, FakeEmbedding(), source)

    result = await tool.search("杭州 景点 景区 博物馆 公园 旅游攻略")

    assert source.calls == 1
    assert [item.title for item in result.items] == ["杭州博物馆与景点指南"]
    assert result.items[0].source_type == "external_web"
    assert result.items[0].metadata["images"][0]["alt"] == "西湖"
    assert result.tools_used == ["web_search", "web_fetch", "semantic_rerank"]
    assert not hasattr(tool, "store")
