from typing import Any


class MockMapProvider:
    """无密钥开发时使用的确定性地图数据，不发起任何外部请求。"""

    source_name = "Mock Map Provider"

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        origin = str(arguments.get("origin") or "宽窄巷子")
        destination = str(arguments.get("destination") or "武侯祠")
        city = str(arguments.get("city") or arguments.get("destination") or "成都")
        if name == "poi_search":
            limit = max(1, min(int(arguments.get("limit", 10)), 20))
            return [
                {
                    "id": "mock-kuanzhai",
                    "name": "宽窄巷子",
                    "type": "风景名胜",
                    "typecode": "110000",
                    "address": "成都市青羊区",
                    "location": "104.055180,30.663213",
                    "city": city,
                    "district": "青羊区",
                    "photo": "",
                    "source": "Mock Map Provider",
                },
                {
                    "id": "mock-wuhouci",
                    "name": "武侯祠",
                    "type": "风景名胜",
                    "typecode": "110000",
                    "address": "成都市武侯区",
                    "location": "104.048655,30.644240",
                    "city": city,
                    "district": "武侯区",
                    "photo": "",
                    "source": "Mock Map Provider",
                },
            ][:limit]
        if name == "weather_query":
            return {
                "destination": city,
                "city": city,
                "condition": "多云",
                "temperature": "20-28℃",
                "date": "",
                "forecasts": [],
                "source": "Mock Map Provider",
            }
        if name == "distance_measure":
            return {
                "origin": origin,
                "destination": destination,
                "distance_km": 3.0,
                "driving_duration_minutes": 20,
                "source": "Mock Map Provider",
            }
        modes = {
            "route_transit": ("公交/地铁", 28),
            "route_driving": ("驾车", 20),
            "route_walking": ("步行", 42),
        }
        if name in modes:
            mode, duration = modes[name]
            return {
                "origin": origin,
                "destination": destination,
                "mode": mode,
                "distance_km": 3.0,
                "duration_minutes": duration,
                "steps": [],
                "source": "Mock Map Provider",
            }
        raise RuntimeError(f"Mock Map Provider 不支持工具：{name}")
