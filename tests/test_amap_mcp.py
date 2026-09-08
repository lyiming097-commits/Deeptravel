import json
from typing import Any

import pytest
from mcp import types

from backend.app.maps.amap_mcp import AmapMcpProvider
from backend.app.mcp.client import StreamableHttpMcpClient


class FakeMcpClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.include_railway = False

    async def list_tools(self) -> list[dict[str, Any]]:
        return [{"name": "maps_text_search"}]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        self.calls.append((name, arguments))
        if name == "maps_text_search":
            return {
                "pois": [
                    {
                        "id": "B001",
                        "name": "宽窄巷子景区",
                        "address": "青羊区",
                        "typecode": "110000",
                        "photos": [
                            {"url": "https://example.com/poi.jpg"},
                            {"url": "https://example.com/poi-2.jpg"},
                            {"url": "https://example.com/poi-3.jpg"},
                        ],
                    }
                ]
            }
        if name == "maps_weather":
            return {
                "city": "成都市",
                "forecasts": [
                    {
                        "date": "2026-08-26",
                        "dayweather": "雷阵雨",
                        "nightweather": "多云",
                        "daytemp": "34",
                        "nighttemp": "26",
                        "daywind": "北",
                        "nightwind": "北",
                    }
                ],
            }
        if name == "maps_geo":
            location = (
                "104.055180,30.663213"
                if arguments["address"] == "宽窄巷子"
                else "104.048655,30.644240"
            )
            return {
                "results": [
                    {
                        "location": location,
                        "adcode": "510100",
                        "city": "成都市",
                    }
                ]
            }
        if name == "maps_distance":
            return {"results": [{"distance": "2948", "duration": "1263"}]}
        if name in {"maps_direction_driving", "maps_direction_walking"}:
            return {
                "paths": [
                    {
                        "distance": "2948",
                        "duration": "1263",
                        "steps": [{"instruction": "向南行驶"}],
                    }
                ]
            }
        if name == "maps_direction_transit_integrated":
            segments: list[dict[str, Any]] = [
                {"bus": {"buslines": [{"name": "蓉城观光7号线"}]}},
            ]
            if self.include_railway:
                segments.insert(0, {"railway": {"name": "G1234(郑州东-杭州东)", "trip": "G1234"}})
            return {
                "transits": [
                    {
                        "duration": "1492",
                        "walking_distance": "395",
                        "cost": "3.0",
                        "segments": segments,
                    }
                ]
            }
        raise AssertionError(f"未预期的工具：{name}")


class DirectionalRouteMcpClient(FakeMcpClient):
    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        if name in {"maps_direction_driving", "maps_direction_walking"}:
            return {
                "paths": [{
                    "distance": "190",
                    "duration": "180",
                    "steps": [
                        {"orientation": "东", "distance": "70"},
                        {"orientation": "北", "distance": "90"},
                    ],
                }]
            }
        return await super().call_tool(name, arguments)


class OrderedPoiClient(FakeMcpClient):
    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        if name == "maps_text_search":
            return {
                "pois": [
                    {"id": "P1", "name": "城市公园", "type": "公园", "typecode": "110101"},
                    {"id": "P2", "name": "普通景点", "type": "风景名胜", "typecode": "110000"},
                    {"id": "P3", "name": "西湖风景名胜区", "type": "风景名胜", "typecode": "110000"},
                ]
            }
        if name == "maps_search_detail":
            return {}
        return await super().call_tool(name, arguments)


class FlakyGeocodeClient(FakeMcpClient):
    def __init__(self) -> None:
        super().__init__()
        self.geocode_attempts: dict[str, int] = {}

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        if name == "maps_geo":
            address = str(arguments.get("address") or "")
            self.geocode_attempts[address] = self.geocode_attempts.get(address, 0) + 1
            if self.geocode_attempts[address] == 1:
                raise RuntimeError("transient geocode failure")
            return {
                "results": [
                    {
                        "location": "116.410829,39.881913",
                        "adcode": "110101",
                        "city": "北京市",
                    }
                ]
            }
        return await super().call_tool(name, arguments)


def test_streamable_http_client_decodes_json_text_content() -> None:
    result = types.CallToolResult(
        content=[types.TextContent(type="text", text=json.dumps({"city": "成都"}))]
    )

    assert StreamableHttpMcpClient._decode_result(result) == {"city": "成都"}


def test_streamable_http_client_adds_key_without_exposing_it_in_sanitised_error() -> None:
    client = StreamableHttpMcpClient("https://mcp.amap.com/mcp?source=test", "secret-key")

    assert "key=secret-key" in client._authenticated_url()
    safe = client._sanitise(
        "request https://mcp.amap.com/mcp?key=secret-key&source=test failed"
    )
    assert "secret-key" not in safe
    assert "key=<redacted>" in safe


def test_amap_photo_parser_prefers_large_and_protocol_relative_urls() -> None:
    urls = AmapMcpProvider._photo_urls(
        {
            "thumbnail": "https://img.example/thumb.jpg",
            "large_url": "//store.is.autonavi.com/poi-large.jpg",
        },
        limit=2,
    )

    assert urls == ["https://store.is.autonavi.com/poi-large.jpg"]


def test_amap_photo_parser_accepts_common_image_alias_fields() -> None:
    urls = AmapMcpProvider._photo_urls(
        {"img_url": "https://img.example/large.jpg", "picurl": "https://img.example/other.jpg"},
        limit=2,
    )

    assert urls == ["https://img.example/large.jpg"]


def test_amap_photo_parser_deduplicates_cdn_renditions() -> None:
    urls = AmapMcpProvider._photo_urls(
        [
            "https://img.example/longmen.jpg?width=640",
            "https://IMG.EXAMPLE/longmen.jpg?width=1200",
            "https://img.example/longmen-2.jpg",
        ],
        limit=2,
    )

    assert urls == [
        "https://img.example/longmen.jpg?width=640",
        "https://img.example/longmen-2.jpg",
    ]


@pytest.mark.asyncio
async def test_amap_location_enrichment_retries_transient_failures() -> None:
    client = FlakyGeocodeClient()
    provider = AmapMcpProvider("https://mcp.amap.com/mcp", "key", client=client)

    enriched = await provider.enrich_poi_locations(
        [{"name": "天坛公园", "location": "", "city": "北京"}], "北京"
    )

    assert enriched[0]["location"] == "116.410829,39.881913"
    assert client.geocode_attempts["天坛公园"] == 2


@pytest.mark.asyncio
async def test_amap_poi_search_prioritises_famous_result_before_applying_limit(monkeypatch) -> None:
    client = OrderedPoiClient()
    provider = AmapMcpProvider("https://mcp.amap.com/mcp", "key", client=client)

    async def no_commons(*args: Any, **kwargs: Any) -> list[str]:
        return []

    monkeypatch.setattr(provider, "_commons_photos", no_commons)
    pois = await provider.call_tool(
        "poi_search", {"keywords": "杭州景点", "city": "杭州", "limit": 2}
    )
    assert len(pois) == 2
    assert pois[0]["name"] == "西湖风景名胜区"


@pytest.mark.asyncio
async def test_amap_poi_search_can_defer_slow_detail_enrichment(monkeypatch) -> None:
    client = OrderedPoiClient()
    provider = AmapMcpProvider("https://mcp.amap.com/mcp", "key", client=client)
    calls = {"locations": 0, "media": 0}

    async def locations(items: list[dict[str, Any]], *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        calls["locations"] += 1
        return items

    async def media(items: list[dict[str, Any]], *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        calls["media"] += 1
        return items

    monkeypatch.setattr(provider, "enrich_poi_locations", locations)
    monkeypatch.setattr(provider, "_enrich_poi_photos", media)

    pois = await provider.call_tool(
        "poi_search",
        {
            "keywords": "杭州景点",
            "city": "杭州",
            "limit": 2,
            "enrich_details": False,
        },
    )

    assert len(pois) == 2
    assert calls == {"locations": 0, "media": 0}


def test_amap_route_polyline_extracts_ordered_geometry_from_steps() -> None:
    polyline = AmapMcpProvider._route_polyline(
        {
            "steps": [
                {"instruction": "向东", "polyline": "113.62,34.74;113.63,34.75"},
                {"instruction": "向南", "polyline": "113.63,34.75;113.64,34.73"},
            ]
        }
    )

    assert polyline == [
        "113.62,34.74",
        "113.63,34.75",
        "113.64,34.73",
    ]


def test_amap_route_estimates_non_straight_shape_from_observed_steps() -> None:
    polyline = AmapMcpProvider._estimate_step_polyline(
        [
            {"orientation": "东", "distance": "40"},
            {"orientation": "北", "distance": "100米"},
            {"orientation": "西", "distance": "50"},
        ],
        "120.130396,30.259242",
        "120.132000,30.260000",
    )

    assert len(polyline) == 4
    assert polyline[0] == "120.130396,30.259242"
    assert polyline[-1] == "120.132,30.26"
    # The middle points retain the turn observations instead of collapsing to
    # the endpoint-to-endpoint straight segment.
    assert len(set(polyline[1:-1])) == 2


def test_commons_photo_title_must_match_requested_landmark() -> None:
    assert AmapMcpProvider._commons_title_matches(
        "File:Longmen Grottoes in Luoyang.jpg", "龙门石窟", "洛阳", ""
    ) is False
    assert AmapMcpProvider._commons_title_matches(
        "File:杭州西湖 West Lake.jpg", "杭州西湖风景名胜区", "杭州", "West Lake"
    ) is True
    assert AmapMcpProvider._commons_title_matches(
        "File:Beijing hotel.jpg", "杭州西湖", "杭州", "West Lake"
    ) is False


def test_commons_photo_title_supports_ningbo_landmark_aliases() -> None:
    assert AmapMcpProvider._commons_title_matches(
        "File:Ningbo Tianyi Pavilion.jpg",
        "天一阁",
        "宁波",
        "Ningbo Tianyi Pavilion",
    ) is True


def test_famous_attraction_priority_beats_generic_city_results() -> None:
    west_lake = {"name": "西湖风景名胜区", "type": "风景名胜", "typecode": "110000"}
    generic_park = {"name": "城市公园", "type": "公园", "typecode": "110101"}

    assert AmapMcpProvider._poi_priority(west_lake, "杭州 景点") > AmapMcpProvider._poi_priority(
        generic_park, "杭州 景点"
    )
    assert AmapMcpProvider._likely_attraction(
        {"name": "天一阁", "type": "名胜古迹", "typecode": ""}
    ) is True


@pytest.mark.asyncio
async def test_amap_mcp_normalises_poi_and_forecast_weather() -> None:
    client = FakeMcpClient()
    provider = AmapMcpProvider("https://mcp.amap.com/mcp", "key", client=client)

    pois = await provider.call_tool(
        "poi_search", {"keywords": "宽窄巷子", "city": "成都", "limit": 3}
    )
    weather = await provider.call_tool("weather_query", {"city": "成都"})

    assert pois[0]["name"] == "宽窄巷子景区"
    assert pois[0]["photo"] == "https://example.com/poi.jpg"
    assert pois[0]["photos"] == [
        "https://example.com/poi.jpg",
        "https://example.com/poi-2.jpg",
    ]
    assert pois[0]["source"] == "高德地图 MCP Streamable HTTP"
    assert weather["condition"] == "雷阵雨转多云"
    assert weather["temperature"] == "26-34℃"
    assert client.calls[0] == (
        "maps_text_search",
        {"keywords": "宽窄巷子", "city": "成都", "citylimit": True},
    )


@pytest.mark.asyncio
async def test_amap_mcp_geocodes_once_then_calls_distance_and_transit() -> None:
    client = FakeMcpClient()
    provider = AmapMcpProvider("https://mcp.amap.com/mcp", "key", client=client)
    arguments = {"origin": "宽窄巷子", "destination": "武侯祠", "city": "成都"}

    distance = await provider.call_tool("distance_measure", arguments)
    route = await provider.call_tool("route_transit", arguments)

    assert distance["distance_km"] == pytest.approx(2.95)
    assert distance["driving_duration_minutes"] == 22
    assert route["duration_minutes"] == 25
    assert route["walking_distance_km"] == pytest.approx(0.4)
    assert [name for name, _ in client.calls].count("maps_geo") == 2
    assert client.calls[-1][0] == "maps_direction_transit_integrated"
    assert client.calls[-1][1]["city"] == "成都"


@pytest.mark.asyncio
async def test_amap_mcp_exposes_observed_railway_leg_in_transit_mode() -> None:
    client = FakeMcpClient()
    client.include_railway = True
    provider = AmapMcpProvider("https://mcp.amap.com/mcp", "key", client=client)

    route = await provider.call_tool(
        "route_transit",
        {"origin": "郑州", "destination": "杭州", "city": ""},
    )

    assert route["mode"] == "高铁 + 公交/地铁"
    assert route["railways"] == [{"name": "G1234(郑州东-杭州东)", "trip": "G1234"}]


@pytest.mark.asyncio
async def test_amap_mcp_supports_driving_and_walking_routes() -> None:
    client = FakeMcpClient()
    provider = AmapMcpProvider("https://mcp.amap.com/mcp", "key", client=client)
    arguments = {
        "origin": "104.055180,30.663213",
        "destination": "104.048655,30.644240",
    }

    driving = await provider.call_tool("route_driving", arguments)
    walking = await provider.call_tool("route_walking", arguments)

    assert driving["mode"] == "驾车"
    assert walking["mode"] == "步行"
    assert driving["distance_km"] == pytest.approx(2.95)
    assert driving["duration_minutes"] == 22


@pytest.mark.asyncio
async def test_amap_route_uses_directional_shape_when_mcp_omits_geometry() -> None:
    provider = AmapMcpProvider(
        "https://mcp.amap.com/mcp", "key", client=DirectionalRouteMcpClient()
    )
    route = await provider.call_tool(
        "route_driving",
        {
            "origin": "宽窄巷子",
            "destination": "武侯祠",
            "city": "成都",
        },
    )

    assert len(route["polyline"]) == 3
    assert route["polyline_source"] == "step_direction_estimate"


def test_amap_transit_shape_uses_walking_observations_without_fake_endpoint_line() -> None:
    polyline = AmapMcpProvider._transit_step_polyline(
        {
            "segments": [
                {
                    "walking": {
                        "steps": [
                            {"orientation": "东", "distance": "80"},
                            {"orientation": "南", "distance": "60"},
                        ]
                    },
                    "bus": {"buslines": [{"name": "505路"}]},
                }
            ]
        },
        "120.130396,30.259242",
        "120.132000,30.258000",
    )

    assert len(polyline) == 3
    assert polyline[0] == "120.130396,30.259242"
    assert polyline[-1] == "120.132,30.258"
