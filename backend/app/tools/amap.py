from typing import Any

from backend.app.maps import MapProvider


class AmapMcpTool:
    """Agent 与高德 MCP Provider 之间的工具边界。"""

    names = frozenset(
        {
            "poi_search",
            "weather_query",
            "route_transit",
            "route_driving",
            "route_walking",
            "distance_measure",
        }
    )

    def __init__(self, provider: MapProvider) -> None:
        self.provider = provider

    async def execute(self, name: str, arguments: dict[str, Any]) -> Any:
        if name not in self.names:
            raise RuntimeError(f"高德 MCP 工具类不支持：{name}")
        return await self.provider.call_tool(name, arguments)

    async def search_pois(
        self,
        keywords: str,
        city: str,
        limit: int = 10,
        *,
        enrich_details: bool = True,
    ) -> list[dict[str, Any]]:
        result = await self.execute(
            "poi_search",
            {
                "keywords": keywords,
                "city": city,
                "limit": limit,
                "enrich_details": enrich_details,
            },
        )
        return result if isinstance(result, list) else []

    async def enrich_poi_media(
        self,
        places: list[dict[str, Any]],
        keywords: str = "",
        city: str = "",
    ) -> list[dict[str, Any]]:
        """Fetch optional POI photos once after candidates are consolidated.

        Itinerary planning may issue several broad and supplemental searches.
        Fetching detail/Commons photos during every search repeats the slowest
        network fan-out and can consume the complete Agent time budget.  Map
        coordinates remain independent and are enriched before this step.
        """

        items = [dict(item) for item in places if isinstance(item, dict)]
        enricher = getattr(self.provider, "enrich_poi_media", None)
        if not callable(enricher):
            return items
        try:
            result = await enricher(items, keywords, city)
        except (RuntimeError, ValueError, OSError):
            return items
        return result if isinstance(result, list) else items

    async def enrich_poi_locations(
        self, places: list[dict[str, Any]], city: str = ""
    ) -> list[dict[str, Any]]:
        """Resolve missing coordinates without coupling them to POI photos."""

        items = [dict(item) for item in places if isinstance(item, dict)]
        enricher = getattr(self.provider, "enrich_poi_locations", None)
        if callable(enricher):
            try:
                result = await enricher(items, city)
            except (RuntimeError, ValueError, OSError):
                return items
            return result if isinstance(result, list) else items

        # Compatibility fallback for alternate map providers. Resolve only
        # missing locations and preserve all original POI fields.
        for item in items:
            if item.get("location") or not item.get("name"):
                continue
            try:
                resolved = await self.resolve_poi(str(item["name"]), city)
            except (RuntimeError, ValueError, OSError):
                continue
            location = str(resolved.get("location") or "").strip()
            if location:
                item["location"] = location
                for key in ("address", "city", "district"):
                    if not item.get(key) and resolved.get(key):
                        item[key] = resolved[key]
        return items

    async def resolve_poi(self, entity: str, city: str = "") -> dict[str, Any]:
        """Resolve an arbitrary place entity to a canonical map POI."""

        entity = entity.strip()
        if not entity:
            return {}
        resolver = getattr(self.provider, "resolve_poi", None)
        if callable(resolver):
            result = await resolver(entity, city)
            if not isinstance(result, dict):
                return {}
            name = str(result.get("name") or "").strip()
            if name and entity not in name and name not in entity:
                # A text-search fallback may return a popular but unrelated
                # POI.  Never relabel the user's area with that result.
                return {}
            return result
        items = await self.search_pois(entity, city, limit=8)
        if not items:
            return {}

        def score(item: dict[str, Any]) -> tuple[int, int]:
            name = str(item.get("name") or "").strip()
            exact = int(name == entity)
            contains = int(entity in name or name in entity)
            return exact, contains

        best = max(items, key=score)
        name = str(best.get("name") or "").strip()
        if name and entity not in name and name not in entity:
            return {}
        return {**best, "query_entity": entity}

    async def search_nearby(
        self,
        keywords: str,
        location: str,
        *,
        radius: int = 3000,
        limit: int = 10,
        city: str = "",
    ) -> list[dict[str, Any]]:
        """Search around a resolved POI, falling back to city text search."""

        resolver = getattr(self.provider, "search_nearby", None)
        if callable(resolver):
            result = await resolver(
                keywords, location, radius=radius, limit=limit
            )
            return result if isinstance(result, list) else []
        return await self.search_pois(keywords, city, limit)


    async def weather(self, city: str) -> dict[str, Any]:
        result = await self.execute("weather_query", {"city": city})
        return result if isinstance(result, dict) else {}

    async def route(
        self, mode_tool: str, origin: str, destination: str, city: str = ""
    ) -> dict[str, Any]:
        if not mode_tool.startswith("route_"):
            raise RuntimeError(f"无效的路线工具：{mode_tool}")
        result = await self.execute(
            mode_tool,
            {"origin": origin, "destination": destination, "city": city},
        )
        return result if isinstance(result, dict) else {}

    async def distance(
        self, origin: str, destination: str, city: str = ""
    ) -> dict[str, Any]:
        result = await self.execute(
            "distance_measure",
            {"origin": origin, "destination": destination, "city": city},
        )
        return result if isinstance(result, dict) else {}

    def citation(self, title: str, metadata: dict[str, Any]) -> dict[str, Any]:
        source = getattr(self.provider, "source_name", "高德地图 MCP")
        source_type = "mock_map" if source.startswith("Mock") else "map_mcp"
        return {
            "type": source_type,
            "chunk_id": None,
            "title": f"{source} {title}",
            "url": None,
            "similarity": None,
            "metadata": metadata,
        }
