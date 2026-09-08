from datetime import timedelta
from typing import Any

import pytest

from backend.app.agent.route_agent import RoutePlanningAgent
from backend.app.agent.route_helpers import clean_railway_station_query
from backend.app.agent.route_workflows import resolve_railway_station
from backend.app.railways import RailwayMcpProvider
from backend.app.tools import RailwayMcpTool


class FakeRailwayClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        self.calls.append((name, arguments))
        if name == "query-tickets":
            return {
                "success": True,
                "count": 1,
                "trains": [{"train_no": "G123", "seats": {"second_class": "有"}}],
            }
        return {"success": True}


@pytest.mark.asyncio
async def test_railway_provider_calls_official_tool_names_without_api_key() -> None:
    client = FakeRailwayClient()
    provider = RailwayMcpProvider("http://127.0.0.1:8200/mcp", client=client)
    tool = RailwayMcpTool(provider)

    result = await tool.tickets("郑州", "杭州", "2026-09-01")

    assert result["trains"][0]["train_no"] == "G123"
    assert client.calls == [
        (
            "query-tickets",
            {
                "from_station": "郑州",
                "to_station": "杭州",
                "train_date": "2026-09-01",
            },
        )
    ]


def test_railway_provider_decodes_mcp_text_envelope() -> None:
    payload = {
        "result": {
            "content": [
                {
                    "type": "text",
                    "text": '{"success": true, "count": 0, "trains": []}',
                }
            ]
        }
    }

    assert RailwayMcpProvider._decode_payload(payload) == {
        "success": True,
        "count": 0,
        "trains": [],
    }


def test_route_agent_distinguishes_cross_city_from_city_internal() -> None:
    assert RoutePlanningAgent.is_cross_city("郑州", "杭州", "", "郑州到杭州")
    assert not RoutePlanningAgent.is_cross_city("西湖", "灵隐寺", "杭州", "西湖到灵隐寺")
    assert RoutePlanningAgent.extract_train_date("郑州到杭州，2026年9月1日", {}) == (
        "2026-09-01"
    )


def test_route_parser_keeps_landmark_suffix_on_city_endpoint() -> None:
    parsed = RoutePlanningAgent.extract_parameters("郑州到洛阳龙门石窟")

    assert parsed["origin"] == "郑州"
    assert parsed["destination"] == "洛阳龙门石窟"


def test_route_parser_removes_train_query_suffix() -> None:
    parsed = RoutePlanningAgent.extract_parameters(
        "我想查询后天（2026年8月30日）郑州到上海的车次"
    )

    assert parsed["origin"] == "郑州"
    assert parsed["destination"] == "上海"


def test_route_parser_removes_relative_date_from_destination() -> None:
    parsed = RoutePlanningAgent.extract_parameters("郑州到北京明天的高铁")

    assert parsed["origin"] == "郑州"
    assert parsed["destination"] == "北京"


def test_route_parser_handles_departure_phrase_before_date() -> None:
    parsed = RoutePlanningAgent.extract_parameters("从郑州出发，明天到北京")

    assert parsed["origin"] == "郑州"
    assert parsed["destination"] == "北京"


def test_route_parser_normalizes_relative_days_and_transport_suffix() -> None:
    message = "2天后从郑州坐火车去大连"
    parsed = RoutePlanningAgent.extract_parameters(message)

    assert parsed["origin"] == "郑州"
    assert parsed["destination"] == "大连"
    assert RoutePlanningAgent.extract_train_date(message, {}) == (
        RoutePlanningAgent._today() + timedelta(days=2)
    ).isoformat()


def test_route_map_points_keep_only_verified_endpoint_coordinates() -> None:
    points = RoutePlanningAgent._map_points(
        {
            "origin_location": "113.6254,34.7466",
            "destination_location": "120.1536,30.2875",
        },
        "郑州东站",
        "杭州东站",
    )

    assert points == [
        {"name": "郑州东站", "location": "113.6254,34.7466", "address": ""},
        {"name": "杭州东站", "location": "120.1536,30.2875", "address": ""},
    ]
    assert RoutePlanningAgent._map_points(
        {"origin_location": "invalid", "destination_location": "200,95"},
        "郑州",
        "杭州",
    ) == []


def test_route_parser_combines_previous_route_turn_with_follow_up_date() -> None:
    context = "从郑州到大连\n两天后出发"
    parsed = RoutePlanningAgent.extract_parameters(context)

    assert parsed["origin"] == "郑州"
    assert parsed["destination"] == "大连"
    assert RoutePlanningAgent.extract_train_date(context, {}) == (
        RoutePlanningAgent._today() + timedelta(days=2)
    ).isoformat()


def test_railway_fallback_reports_total_and_bounded_display() -> None:
    trains = [{"train_no": f"G{i:03}"} for i in range(10)]
    answer = RoutePlanningAgent._railway_fallback(
        {
            "train_date": "2026-09-01",
            "origin": "郑州",
            "destination": "上海",
            "trains": trains,
            "total_trains": 86,
        }
    )
    assert "查到 86 趟直达车次，先列出 9 趟" in answer


def test_clean_railway_station_query_removes_conversational_suffixes() -> None:
    assert clean_railway_station_query("郑州高铁站") == "郑州"
    assert clean_railway_station_query("南京南站") == "南京南"
    assert clean_railway_station_query("郑州市") == "郑州"


@pytest.mark.asyncio
async def test_resolve_railway_station_uses_exact_mcp_name() -> None:
    class FakeRailwayTool:
        async def stations(self, query: str, limit: int = 10) -> dict[str, Any]:
            return {"stations": [{"name": "郑州"}, {"name": "郑州东"}]}

    assert await resolve_railway_station(FakeRailwayTool(), "郑州高铁站") == "郑州"


@pytest.mark.asyncio
async def test_route_dynamic_station_lookup_detects_unknown_city_pair() -> None:
    class FakeRailwayTool:
        configured = True

        async def stations(self, query: str, limit: int = 10) -> dict[str, Any]:
            return {
                "success": True,
                "stations": [{"name": f"{query}站", "code": "AAA"}],
            }

    agent = object.__new__(RoutePlanningAgent)
    agent.railway_tool = FakeRailwayTool()

    assert await agent.detect_cross_city("拉萨", "林芝", "", "拉萨到林芝")


@pytest.mark.asyncio
async def test_route_dynamic_station_lookup_skips_local_landmarks() -> None:
    class FakeRailwayTool:
        configured = True

        async def stations(self, query: str, limit: int = 10) -> dict[str, Any]:
            raise AssertionError("景点路线不应先查询铁路车站")

    agent = object.__new__(RoutePlanningAgent)
    agent.railway_tool = FakeRailwayTool()

    assert not await agent.detect_cross_city("西湖", "灵隐寺", "", "西湖到灵隐寺")
