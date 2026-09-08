from typing import Any

import pytest

from backend.app.agent.base import infer_destination
from backend.app.agent.intent import (
    TravelIntentClassifier,
    extract_area_entity,
    rule_classify,
)
from backend.app.config import Settings
from backend.app.tools.amap import AmapMcpTool
from backend.app.tools.relevance import extract_landmark_terms


@pytest.mark.parametrize(
    ("message", "intent"),
    [
        ("想去郑州玩两天", "itinerary"),
        ("杭州有哪些景点推荐", "attraction"),
        ("从郑州到杭州怎么走", "transportation"),
        ("洛阳有什么美食", "food"),
        ("北京购物去哪里", "shopping"),
    ],
)
def test_rule_intent_supports_more_travel_scenarios(message: str, intent: str) -> None:
    assert rule_classify(message).intent == intent


@pytest.mark.parametrize(
    ("message", "destination"),
    [
        ("宁波两天行程", "宁波"),
        ("张掖三日游", "张掖"),
        ("想去乌鲁木齐", "乌鲁木齐"),
        ("我想去宁波看天一阁", "宁波"),
    ],
)
def test_destination_fallback_supports_cities_outside_static_examples(
    message: str, destination: str
) -> None:
    assert infer_destination(message, "") == destination


@pytest.mark.parametrize(
    ("message", "area"),
    [
        ("杭州西溪湿地附近酒店", "杭州西溪湿地"),
        ("住在灵隐寺附近的民宿", "灵隐寺"),
        ("外滩周边有哪些住宿", "外滩"),
    ],
)
def test_area_entity_extraction_is_not_a_fixed_word_list(message: str, area: str) -> None:
    assert extract_area_entity(message) == area


def test_landmark_extraction_keeps_the_place_not_the_question_prefix() -> None:
    assert extract_landmark_terms("我想问龙门石窟怎么玩") == ["龙门石窟"]
    assert extract_landmark_terms("我想去宁波看天一阁") == ["天一阁"]


class FakeIntentLlm:
    configured = True

    def __init__(self) -> None:
        self.calls: list[list[dict[str, str]]] = []

    async def chat_json(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        self.calls.append(messages)
        return {
            "intent": "food",
            "confidence": 0.94,
            "entities": {"destination": "洛阳", "area": "老城十字街"},
        }


class NormalisingIntentLlm(FakeIntentLlm):
    async def chat_json(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        return {
            "intent": "attraction",
            "confidence": 0.9,
            "entities": {"destination": "宁波市", "area": "天一阁景区"},
        }


class UnexpectedIntentLlm(FakeIntentLlm):
    async def chat_json(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        raise AssertionError("高置信度明确请求不应调用远程模型")


@pytest.mark.asyncio
async def test_intent_classifier_prefers_llm_and_keeps_grounded_entities() -> None:
    llm = FakeIntentLlm()
    classifier = TravelIntentClassifier(Settings(_env_file=None), llm)  # type: ignore[arg-type]

    decision = await classifier.classify("洛阳老城十字街吃什么")

    assert decision.intent == "food"
    assert decision.source == "llm"
    assert decision.entities == {"destination": "洛阳", "area": "老城十字街"}
    assert llm.calls


@pytest.mark.asyncio
async def test_intent_classifier_normalises_grounded_city_and_landmark_suffixes() -> None:
    decision = await TravelIntentClassifier(
        Settings(_env_file=None), NormalisingIntentLlm()  # type: ignore[arg-type]
    ).classify("宁波天一阁景区有哪些景点")
    assert decision.entities["destination"] == "宁波"
    assert decision.entities["area"] == "天一阁"


@pytest.mark.asyncio
async def test_intent_classifier_skips_remote_call_for_obvious_itinerary() -> None:
    decision = await TravelIntentClassifier(
        Settings(_env_file=None), UnexpectedIntentLlm()  # type: ignore[arg-type]
    ).classify("帮我规划杭州三日游")

    assert decision.intent == "itinerary"
    assert decision.source == "rules"
    assert decision.confidence >= 0.9


class FakePoiProvider:
    source_name = "高德地图 MCP"

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        assert name == "poi_search"
        return [
            {
                "name": arguments["keywords"],
                "type": "风景名胜",
                "city": arguments.get("city") or "上海",
                "location": "121.4903,31.2397",
            }
        ]


@pytest.mark.asyncio
async def test_amap_tool_resolves_arbitrary_area_poi() -> None:
    tool = AmapMcpTool(FakePoiProvider())

    result = await tool.resolve_poi("外滩", "上海")

    assert result["name"] == "外滩"
    assert result["location"] == "121.4903,31.2397"
    assert result["query_entity"] == "外滩"
