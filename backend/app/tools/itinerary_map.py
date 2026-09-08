"""地图展示数据工具。

地图渲染在前端完成，Agent 只需要把经过 Provider 校验的坐标整理成稳定
的数据结构。本工具集中处理行程景点和路线端点两种地图数据，避免各个 Agent
重复实现坐标校验逻辑。
"""

from typing import Any


class ItineraryMapTool:
    """将地图观测转换为前端可消费的地图点位。"""

    name = "itinerary_map"

    @staticmethod
    def _valid_location(value: Any, *, preserve_format: bool = False) -> str:
        if isinstance(value, (list, tuple)) and len(value) >= 2:
            raw = f"{value[0]},{value[1]}"
        elif isinstance(value, dict):
            raw = (
                f"{value.get('longitude', value.get('lng', ''))},"
                f"{value.get('latitude', value.get('lat', ''))}"
            )
        else:
            raw = str(value or "").strip()
        parts = raw.split(",")
        if len(parts) != 2:
            return ""
        try:
            longitude, latitude = float(parts[0]), float(parts[1])
        except (TypeError, ValueError):
            return ""
        if not (-180 <= longitude <= 180 and -90 <= latitude <= 90):
            return ""
        if preserve_format:
            # Keep the provider's textual precision (for example ``120.10``)
            # so persisted itinerary payloads remain stable across refactors.
            return f"{parts[0].strip()},{parts[1].strip()}"
        return f"{longitude},{latitude}"

    @classmethod
    def has_valid_location(cls, value: Any) -> bool:
        """Return whether a provider value can safely become a map marker."""

        return bool(cls._valid_location(value))

    @classmethod
    def build_points(
        cls, places: list[dict[str, Any]], days_plan: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Build compact, grounded points for an itinerary map.

        A point is emitted only when the map provider supplied a valid
        ``longitude,latitude`` coordinate. Photos are optional and copied only
        from the provider response; no location or image is invented here.
        """
        day_by_name: dict[str, int] = {}
        for day in days_plan:
            for name in day.get("activities", []):
                day_by_name.setdefault(str(name), int(day.get("day", 0)))
        points: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for place in places:
            if not isinstance(place, dict):
                continue
            name = str(place.get("name") or "").strip()
            location = cls._valid_location(place.get("location"), preserve_format=True)
            if not name or not location:
                continue
            key = (name, location)
            if key in seen:
                continue
            seen.add(key)
            point: dict[str, Any] = {
                "name": name,
                "location": location,
                "address": str(place.get("address") or "").strip(),
                "day": day_by_name.get(name),
            }
            photo = str(place.get("photo") or "").strip()
            if not photo and isinstance(place.get("photos"), list):
                photo = next(
                    (
                        str(value).strip()
                        for value in place["photos"]
                        if isinstance(value, str)
                        and value.strip().startswith(("https://", "http://"))
                    ),
                    "",
                )
            if photo.startswith(("https://", "http://")):
                point["photo"] = photo
            points.append(point)
        return points[:30]

    @classmethod
    def build_route_points(
        cls, route: dict[str, Any], origin: str, destination: str
    ) -> list[dict[str, str]]:
        """Build verified endpoint points from a route observation."""
        points: list[dict[str, str]] = []
        for name, location_key, address_key in (
            (origin, "origin_location", "origin_address"),
            (destination, "destination_location", "destination_address"),
        ):
            location = cls._valid_location(route.get(location_key))
            label = str(name or "").strip()
            if not location or not label:
                continue
            points.append(
                {
                    "name": label,
                    "location": location,
                    "address": str(route.get(address_key) or "").strip(),
                }
            )
        return points

    @classmethod
    async def resolve_route_points(
        cls, amap_tool: Any, origin: str, destination: str
    ) -> list[dict[str, str]]:
        """Resolve endpoint names through the injected map tool.

        This optional enrichment is intentionally kept in the tool layer. A
        missing map provider never prevents the route Agent from answering.
        """
        resolver = getattr(amap_tool, "resolve_poi", None)
        provider = getattr(amap_tool, "provider", None)
        source_name = str(getattr(provider, "source_name", ""))
        if not callable(resolver) or not source_name or source_name.startswith("Mock"):
            return []
        import asyncio

        try:
            resolved = await asyncio.gather(
                resolver(str(origin).strip(), ""),
                resolver(str(destination).strip(), ""),
                return_exceptions=True,
            )
        except (RuntimeError, ValueError, OSError):
            return []
        points: list[dict[str, str]] = []
        for name, item in zip((origin, destination), resolved):
            if not isinstance(item, dict):
                continue
            location = cls._valid_location(item.get("location"))
            label = str(name or item.get("name") or "").strip()
            if not location or not label:
                continue
            points.append(
                {
                    "name": label,
                    "location": location,
                    "address": str(item.get("address") or "").strip(),
                }
            )
        return points
