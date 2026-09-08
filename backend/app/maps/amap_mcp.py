import asyncio
import math
import re
from typing import Any, Protocol
from urllib.parse import unquote, urlsplit

import httpx

from backend.app.mcp.client import StreamableHttpMcpClient

MAX_POI_PHOTOS = 2

# Wikimedia uses English/romanised file titles for many Chinese landmarks.
# This is an image-search alias table, not a destination whitelist: unknown
# POIs still use their Amap photos, while well-known sights get a safe Commons
# fallback when the map response has no ``photo`` field.
FAMOUS_ATTRACTION_ALIASES: dict[str, str] = {
    "西湖": "West Lake",
    "灵隐寺": "Lingyin Temple",
    "故宫": "Forbidden City",
    "长城": "Great Wall China",
    "八达岭长城": "Badaling Great Wall",
    "颐和园": "Summer Palace Beijing",
    "天坛": "Temple of Heaven Beijing",
    "外滩": "The Bund Shanghai",
    "东方明珠": "Oriental Pearl Tower",
    "豫园": "Yu Garden Shanghai",
    "拙政园": "Humble Administrator's Garden",
    "虎丘": "Tiger Hill Suzhou",
    "夫子庙": "Confucius Temple Nanjing",
    "中山陵": "Sun Yat-sen Mausoleum Nanjing",
    "秦淮河": "Qinhuai River Nanjing",
    "龙门石窟": "Longmen Grottoes",
    "白马寺": "White Horse Temple Luoyang",
    "兵马俑": "Terracotta Army",
    "大雁塔": "Giant Wild Goose Pagoda Xian",
    "华清宫": "Huaqing Palace Xian",
    "宽窄巷子": "Kuanzhai Alley Chengdu",
    "武侯祠": "Wuhou Shrine Chengdu",
    "都江堰": "Dujiangyan",
    "洪崖洞": "Hongya Cave Chongqing",
    "岳麓山": "Yuelu Mountain Changsha",
    "橘子洲": "Orange Island Changsha",
    "鼓浪屿": "Gulangyu",
    "张家界": "Zhangjiajie National Forest Park",
    "天一阁": "Ningbo Tianyi Pavilion",
    "月湖": "Ningbo Moon Lake",
    "东钱湖": "Dongqian Lake Ningbo",
    "宁波博物馆": "Ningbo Museum",
    "老外滩": "Ningbo Old Bund",
    "天童寺": "Tiantong Temple Ningbo",
    "阿育王寺": "Ayuwang Temple Ningbo",
    "雪窦山": "Xuedou Mountain",
    "溪口": "Xikou Ningbo",
    "象山影视城": "Xiangshan Movie and Television City",
    "南塘老街": "Nantang Old Street Ningbo",
    "宁波鼓楼": "Ningbo Drum Tower",
}


class McpToolClient(Protocol):
    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any: ...

    async def list_tools(self) -> list[dict[str, Any]]: ...


class AmapMcpProvider:
    """高德远程 MCP Streamable HTTP 工具适配器。"""

    source_name = "高德地图 MCP"

    def __init__(
        self,
        endpoint: str,
        api_key: str,
        timeout: float = 30,
        client: McpToolClient | None = None,
    ) -> None:
        self.client = client or StreamableHttpMcpClient(
            endpoint,
            api_key,
            api_key_query_name="key",
            timeout=timeout,
        )
        self._geocode_cache: dict[tuple[str, str], dict[str, str]] = {}

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        handlers = {
            "poi_search": self._poi_search,
            "weather_query": self._weather_query,
            "route_transit": self._route_transit,
            "route_driving": self._route_driving,
            "route_walking": self._route_walking,
            "distance_measure": self._distance_measure,
        }
        handler = handlers.get(name)
        if handler is None:
            raise RuntimeError(f"高德 MCP 不支持工具：{name}")
        return await handler(arguments)

    async def list_tools(self) -> list[dict[str, Any]]:
        return await self.client.list_tools()

    async def _poi_search(self, arguments: dict[str, Any]) -> list[dict[str, Any]]:
        keywords = self._text(arguments.get("keywords"))
        city = self._text(arguments.get("city"))
        if not keywords:
            raise RuntimeError("POI 搜索关键词不能为空")
        response = self._object(
            await self.client.call_tool(
                "maps_text_search",
                {"keywords": keywords, "city": city, "citylimit": bool(city)},
            ),
            "maps_text_search",
        )
        pois = response.get("pois")
        if not isinstance(pois, list):
            raise RuntimeError("高德 MCP POI 响应缺少 pois 列表")  # noqa: TRY004
        limit = max(1, min(int(arguments.get("limit", 20)), 20))
        normalised = [
            {
                "id": self._text(poi.get("id")),
                "name": self._text(poi.get("name")),
                "type": self._text(poi.get("type")) or self._text(poi.get("typecode")),
                "typecode": self._text(poi.get("typecode")),
                "address": self._text(poi.get("address")),
                "location": self._text(poi.get("location")),
                "city": (
                    self._text(poi.get("city"))
                    or self._text(poi.get("cityname"))
                    or city
                ),
                "district": (
                    self._text(poi.get("district"))
                    or self._text(poi.get("adname"))
                ),
                "photo": self._photo_url(poi.get("photo") or poi.get("photos")),
                "photos": self._photo_urls(poi.get("photos") or poi.get("photo")),
                "business_area": self._text(poi.get("business_area")),
                "alias": self._text(poi.get("alias")),
                "rating": self._poi_rating(poi),
                "source": "高德地图 MCP Streamable HTTP",
            }
            # Read a wider provider window before applying the requested
            # output limit; famous sights can otherwise sit just after the
            # first few generic businesses in a city-wide result.
            for poi in pois[:20]
            if isinstance(poi, dict) and self._text(poi.get("name"))
        ]
        # Amap normally ranks by keyword relevance, but a city-wide “景点”
        # query can place generic parks/facilities before an iconic sight.
        # Apply a small deterministic popularity/relevance tie-breaker while
        # preserving provider order for equal scores. This makes the media
        # enrichment pass see 西湖、龙门石窟等 named attractions first without
        # inventing any POI that the provider did not return.
        normalised.sort(
            key=lambda item: self._poi_priority(item, keywords), reverse=True
        )
        normalised = normalised[:limit]
        # Coordinates are core map data, so resolve them before optional photo
        # fan-out. Detail/Commons image requests can be slow or rate-limited;
        # they must not prevent otherwise valid POIs from appearing on maps.
        normalised = await self.enrich_poi_locations(normalised, city, limit=12)
        normalised = await self._enrich_poi_photos(normalised, keywords, city)
        return normalised

    async def enrich_poi_locations(
        self,
        places: list[dict[str, Any]],
        city: str = "",
        *,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Fill missing POI coordinates with bounded retries.

        Some Amap text-search responses omit ``location`` even for canonical
        attractions. Resolve those names in small batches and retry failures
        sequentially; opening many independent Streamable HTTP sessions at
        once caused intermittent empty coordinates on real devices.
        """

        enriched = [dict(item) for item in places if isinstance(item, dict)]
        candidates = [
            item
            for item in enriched[: max(1, min(limit, 30))]
            if item.get("name") and not self._is_location(self._text(item.get("location")))
        ]
        if not candidates:
            return enriched

        unresolved: list[dict[str, Any]] = []
        for offset in range(0, len(candidates), 3):
            batch = candidates[offset : offset + 3]
            locations = await asyncio.gather(
                *(
                    self._poi_location(
                        str(item.get("name") or ""),
                        str(item.get("city") or city),
                    )
                    for item in batch
                ),
                return_exceptions=True,
            )
            for item, location in zip(batch, locations):
                if isinstance(location, str) and self._is_location(location):
                    item["location"] = location
                else:
                    unresolved.append(item)

        # A short sequential retry is intentionally limited to one pass. It
        # recovers transient MCP/session failures without turning map
        # enrichment into an unbounded request loop.
        for item in unresolved:
            location = await self._poi_location(
                str(item.get("name") or ""),
                str(item.get("city") or city),
            )
            if self._is_location(location):
                item["location"] = location
        return enriched

    async def _enrich_poi_photos(
        self, places: list[dict[str, Any]], keywords: str, city: str
    ) -> list[dict[str, Any]]:
        """Fill missing POI photos from detail MCP and Commons.

        Both text and around-search results use this path.  Amap deployments
        differ in whether photos are returned inline, on ``maps_search_detail``
        or not at all, so treating the three sources uniformly prevents area
        queries (such as “西湖附近景点”) from losing images.
        """

        candidates = [
            item for item in places[:12]
            if len(item.get("photos") or []) < MAX_POI_PHOTOS and item.get("id")
        ]
        if candidates:
            details = await asyncio.gather(
                *(self._poi_detail_photos(str(item["id"])) for item in candidates),
                return_exceptions=True,
            )
            for item, detail in zip(candidates, details):
                if isinstance(detail, list) and detail:
                    merged = self._photo_urls(
                        [item.get("photos") or [], detail], limit=MAX_POI_PHOTOS
                    )
                    if merged:
                        item["photos"] = merged
                        item["photo"] = merged[0]
        image_candidates = [
            item for item in places[:12]
            if self._likely_attraction(item)
            and len(item.get("photos") or []) < MAX_POI_PHOTOS
        ]
        image_candidates.sort(
            key=lambda item: int(self._is_famous_attraction(item)), reverse=True
        )
        # Commons is a fallback, not the primary map source. Keep the
        # network fan-out bounded while ensuring famous attractions are first.
        image_candidates = image_candidates[:8]
        if image_candidates:
            fallback_photos = await asyncio.gather(
                *(
                    self._commons_photos(
                        str(item.get("name") or ""),
                        str(item.get("city") or city),
                    )
                    for item in image_candidates
                ),
                return_exceptions=True,
            )
            for item, photos in zip(image_candidates, fallback_photos):
                if isinstance(photos, list) and photos:
                    merged = self._photo_urls(
                        [item.get("photos") or [], photos], limit=MAX_POI_PHOTOS
                    )
                    if merged:
                        item["photos"] = merged
                        item["photo"] = merged[0]
        return places

    @staticmethod
    def _likely_attraction(item: dict[str, Any]) -> bool:
        text = " ".join(
            str(item.get(key) or "") for key in ("name", "type", "typecode")
        )
        return bool(
            str(item.get("typecode") or "").startswith("110")
            or re.search(
                r"景区|风景|名胜|公园|寺|塔|湖|石窟|洞窟|博物馆|古镇|故居|纪念馆|遗址|"
                r"园|阁|滩|街|城|岛|湾|广场|楼|台|祠|陵|桥|瀑布",
                text,
            )
        )

    @classmethod
    def _poi_rating(cls, item: dict[str, Any]) -> str:
        rating = cls._text(item.get("rating"))
        if rating:
            return rating
        details = item.get("biz_ext")
        return cls._text(details.get("rating")) if isinstance(details, dict) else ""

    @classmethod
    def _poi_priority(cls, item: dict[str, Any], keywords: str) -> tuple[int, float, int]:
        """Rank explicit/famous scenic POIs ahead of generic nearby results."""

        name = str(item.get("name") or "")
        searchable = " ".join(
            str(item.get(key) or "") for key in ("name", "type", "typecode", "alias")
        )
        query = str(keywords or "")
        famous = int(cls._is_famous_attraction(item) and cls._likely_attraction(item))
        exact = int(bool(name) and (name in query or query in name))
        attraction = int(cls._likely_attraction(item))
        rating = 0.0
        for key in ("rating", "score", "importance"):
            try:
                rating = max(rating, float(str(item.get(key) or "")))
            except (TypeError, ValueError):
                continue
        return (famous * 100 + exact * 40 + attraction * 10, rating, len(searchable))

    @staticmethod
    def _is_famous_attraction(item: dict[str, Any]) -> bool:
        name = str(item.get("name") or "")
        return any(keyword in name for keyword in FAMOUS_ATTRACTION_ALIASES)

    async def _commons_photos(self, name: str, city: str) -> list[str]:
        if not name:
            return []
        # Commons commonly titles Chinese landmarks with their English
        # transliteration.  Supplying these aliases lets the generic fallback
        # find images for places such as Ningbo's Tianyi Pavilion and Moon
        # Lake instead of returning photos only for globally famous sights.
        aliases = FAMOUS_ATTRACTION_ALIASES
        search_name = aliases.get(name, "") or next(
            (value for key, value in aliases.items() if key in name), ""
        )
        query = f"{city} {name}"
        if search_name:
            query = f"{query} OR {search_name}"
        params = {
            "action": "query",
            "generator": "search",
            "gsrsearch": query.strip(),
            "gsrnamespace": "6",
            "gsrlimit": "4",
            "prop": "imageinfo",
            "iiprop": "url|mime",
            "iiurlwidth": "1200",
            "format": "json",
        }
        try:
            # Wikimedia can take a few seconds to answer from mainland
            # networks; allow enough time for the famous-attraction fallback
            # instead of silently retaining a small Amap thumbnail.
            async with httpx.AsyncClient(timeout=12, follow_redirects=True) as client:
                response = await client.get(
                    "https://commons.wikimedia.org/w/api.php", params=params,
                    headers={"User-Agent": "DeepTravel/1.0 (travel assistant)"},
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError, OSError):
            return []
        pages = payload.get("query", {}).get("pages", {})
        urls: list[str] = []
        for page in pages.values() if isinstance(pages, dict) else []:
            title = self._text(page.get("title")) if isinstance(page, dict) else ""
            if not self._commons_title_matches(title, name, city, search_name):
                continue
            info = page.get("imageinfo", []) if isinstance(page, dict) else []
            if not info or not isinstance(info[0], dict):
                continue
            image = info[0]
            mime = str(image.get("mime") or "")
            url = str(image.get("thumburl") or image.get("url") or "").strip()
            if mime.startswith("image/") and url.startswith("https://") and url not in urls:
                urls.append(url)
            if len(urls) >= MAX_POI_PHOTOS:
                break
        return urls

    @classmethod
    def _commons_title_matches(
        cls, title: str, name: str, city: str, english_alias: str = ""
    ) -> bool:
        """Reject Wikimedia results whose page title is not this POI.

        Wikimedia's full-text search can return visually attractive but
        unrelated photos for broad Chinese queries. Require a meaningful name
        overlap (or an explicit English alias) before using a fallback image.
        If no overlap is available, returning no image is safer than showing
        the wrong landmark.
        """
        title_text = re.sub(r"[^\w\u4e00-\u9fff]+", "", str(title or "").lower())
        name_text = re.sub(r"[^\w\u4e00-\u9fff]+", "", str(name or "").lower())
        city_text = re.sub(r"[^\w\u4e00-\u9fff]+", "", str(city or "").lower())
        alias_text = re.sub(r"[^\w]+", " ", str(english_alias or "").lower()).strip()
        if name_text and name_text in title_text:
            return True
        # Ignore administrative suffixes when matching Chinese POI names.
        for suffix in ("风景名胜区", "旅游景区", "景区", "风景区"):
            short_name = name_text.removesuffix(suffix)
            if len(short_name) >= 2 and short_name in title_text:
                return True
        if alias_text and all(token in title_text for token in alias_text.split() if len(token) >= 3):
            return True
        # For a Chinese title, a distinctive two-character name fragment is
        # sufficient only when the city also appears, reducing false matches
        # for generic words such as“公园” or“古镇”.
        if city_text and city_text in title_text and len(name_text) >= 4:
            return any(name_text[index : index + 3] in title_text for index in range(len(name_text) - 2))
        return False

    async def _poi_detail_photos(self, poi_id: str) -> list[str]:
        try:
            detail = await self.client.call_tool("maps_search_detail", {"id": poi_id})
        except (RuntimeError, ValueError, OSError):
            return []
        if not isinstance(detail, dict):
            return []
        values: list[Any] = []

        def collect(value: Any) -> None:
            if isinstance(value, dict):
                for key, nested in value.items():
                    key_name = str(key).lower()
                    if any(token in key_name for token in ("photo", "image", "pic")):
                        values.append(nested)
                    # Detail responses differ between MCP deployments; walk
                    # nested ``poi``, ``data`` and ``biz_ext`` objects too.
                    if isinstance(nested, (dict, list)):
                        collect(nested)
            elif isinstance(value, list):
                for nested in value:
                    collect(nested)

        collect(detail)
        urls: list[str] = []
        identities: set[str] = set()
        for value in values:
            for url in self._photo_urls(value):
                identity = self._photo_identity(url)
                if identity and identity not in identities:
                    urls.append(url)
                    identities.add(identity)
                if len(urls) >= MAX_POI_PHOTOS:
                    return urls
        return urls

    async def _poi_location(self, name: str, city: str = "") -> str:
        try:
            resolved = await self._resolve_place(name, city)
        except (RuntimeError, ValueError, OSError):
            return ""
        return resolved.get("location", "")

    async def resolve_poi(self, entity: str, city: str = "") -> dict[str, Any]:
        """Resolve a free-form landmark/area through the Amap POI MCP tool.

        This public method is intentionally separate from route geocoding: an
        accommodation query needs the human-readable POI name, district and
        city as well as coordinates.  Text search handles arbitrary landmarks
        (for example 西溪湿地、灵隐寺、外滩) without a local area dictionary.
        """

        entity = self._text(entity)
        if not entity:
            return {}
        items = await self._poi_search({"keywords": entity, "city": city, "limit": 8})
        if items:
            def score(item: dict[str, Any]) -> tuple[int, int]:
                name = self._text(item.get("name"))
                return int(name == entity), int(entity in name or name in entity)

            best = max(items, key=score)
            detail: dict[str, Any] = {}
            poi_id = self._text(best.get("id"))
            if poi_id:
                try:
                    raw_detail = await self.client.call_tool(
                        "maps_search_detail", {"id": poi_id}
                    )
                    if isinstance(raw_detail, dict):
                        detail = raw_detail
                except (RuntimeError, ValueError):
                    detail = {}
            enriched = {
                **best,
                "name": self._text(detail.get("name")) or best.get("name"),
                "location": self._text(detail.get("location")) or best.get("location"),
                "address": self._text(detail.get("address")) or best.get("address"),
                "city": self._text(detail.get("city")) or best.get("city"),
                "type": self._text(detail.get("type")) or best.get("type"),
                "rating": self._text(detail.get("rating")),
                "open_time": self._text(detail.get("open_time")),
            }
            needs_reverse = not self._text(enriched.get("city")) or not self._text(
                enriched.get("district")
            )
            if needs_reverse and self._is_location(self._text(enriched.get("location"))):
                try:
                    reverse = await self.client.call_tool(
                        "maps_regeocode", {"location": enriched["location"]}
                    )
                    if isinstance(reverse, dict):
                        city_value = reverse.get("city")
                        if isinstance(city_value, list):
                            city_value = city_value[0] if city_value else ""
                        enriched["city"] = self._text(enriched.get("city")) or (
                            self._text(city_value)
                            or self._text(reverse.get("province"))
                        )
                        enriched["district"] = self._text(
                            enriched.get("district")
                        ) or self._text(reverse.get("district"))
                except (RuntimeError, ValueError):
                    pass
            return {
                **enriched,
                "query_entity": entity,
                "resolution_method": "poi_search",
            }
        # Text search may not index a small neighbourhood name.  Geocoding is
        # a useful second map-MCP observation and still returns a canonical
        # coordinate/city for nearby searches.
        try:
            resolved = await self._resolve_place(entity, city)
        except RuntimeError:
            return {}
        return {
            **resolved,
            "name": entity,
            "query_entity": entity,
            "resolution_method": "geocode",
        }

    async def search_nearby(
        self,
        keywords: str,
        location: str,
        *,
        radius: int = 3000,
        limit: int = 10,
        city: str = "",
    ) -> list[dict[str, Any]]:
        """Search around a resolved POI coordinate through Amap MCP."""

        if not self._is_location(location):
            return []
        response = self._object(
            await self.client.call_tool(
                "maps_around_search",
                {
                    "keywords": self._text(keywords),
                    "location": location,
                    "radius": str(max(100, min(radius, 50000))),
                    "strategy": 0,
                },
            ),
            "maps_around_search",
        )
        pois = response.get("pois")
        if not isinstance(pois, list):
            return []
        normalised = [
            {
                "id": self._text(poi.get("id")),
                "name": self._text(poi.get("name")),
                "type": self._text(poi.get("type"))
                or self._text(poi.get("typecode")),
                "typecode": self._text(poi.get("typecode")),
                "address": self._text(poi.get("address")),
                "location": self._text(poi.get("location")),
                "city": self._text(poi.get("city"))
                or self._text(poi.get("cityname")),
                "district": self._text(poi.get("district"))
                or self._text(poi.get("adname")),
                "photo": self._photo_url(poi.get("photo") or poi.get("photos")),
                "photos": self._photo_urls(poi.get("photos") or poi.get("photo")),
                "rating": self._poi_rating(poi),
                "source": "高德地图 MCP Streamable HTTP",
            }
            for poi in pois[: max(1, min(limit, 20))]
            if isinstance(poi, dict) and self._text(poi.get("name"))
        ]
        normalised.sort(
            key=lambda item: self._poi_priority(item, keywords), reverse=True
        )
        return await self._enrich_poi_photos(normalised, keywords, city)

    async def _weather_query(self, arguments: dict[str, Any]) -> dict[str, Any]:
        city = self._text(arguments.get("city"))
        if not city:
            raise RuntimeError("城市不能为空")
        response = self._object(
            await self.client.call_tool("maps_weather", {"city": city}),
            "maps_weather",
        )
        forecasts = response.get("forecasts")
        if not isinstance(forecasts, list) or not forecasts or not isinstance(forecasts[0], dict):
            raise RuntimeError(f"高德 MCP 未返回 {city} 的天气预报")
        today = forecasts[0]
        day_condition = self._text(today.get("dayweather")) or "未知"
        night_condition = self._text(today.get("nightweather"))
        condition = (
            day_condition
            if not night_condition or night_condition == day_condition
            else f"{day_condition}转{night_condition}"
        )
        day_temperature = self._text(today.get("daytemp"))
        night_temperature = self._text(today.get("nighttemp"))
        temperature = (
            f"{night_temperature}-{day_temperature}℃"
            if night_temperature and day_temperature
            else f"{day_temperature or night_temperature}℃"
        )
        return {
            "destination": city,
            "city": self._text(response.get("city")) or city,
            "condition": condition,
            "temperature": temperature,
            "date": self._text(today.get("date")),
            "day_wind": self._text(today.get("daywind")),
            "night_wind": self._text(today.get("nightwind")),
            "forecasts": forecasts,
            "source": "高德地图 MCP Streamable HTTP",
        }

    async def _route_transit(self, arguments: dict[str, Any]) -> dict[str, Any]:
        origin = self._text(arguments.get("origin"))
        destination = self._text(arguments.get("destination"))
        city = self._text(arguments.get("city"))
        start = await self._resolve_place(origin, city)
        end = await self._resolve_place(destination, city)
        response = self._object(
            await self.client.call_tool(
                "maps_direction_transit_integrated",
                {
                    "origin": start["location"],
                    "destination": end["location"],
                    "city": city or start["city"] or start["adcode"],
                    "cityd": city or end["city"] or end["adcode"],
                },
            ),
            "maps_direction_transit_integrated",
        )
        route = response.get("route")
        route_data = route if isinstance(route, dict) else response
        transits = route_data.get("transits")
        if not isinstance(transits, list) or not transits or not isinstance(transits[0], dict):
            raise RuntimeError(f"高德 MCP 未找到从 {origin} 到 {destination} 的公交路线")
        transit = transits[0]
        railways = self._railway_details(transit)
        polyline = self._route_polyline(transit)
        geometry_source = "provider_geometry" if len(polyline) > 1 else ""
        if len(polyline) < 2:
            # Amap's MCP currently returns transit legs/stops but frequently
            # omits the road geometry.  Use the observed walking leg
            # directions/distances to make a route-shaped diagram.  This is
            # deliberately labelled as an estimate; it must never be
            # presented as an exact road trace.
            polyline = self._transit_step_polyline(
                transit, start["location"], end["location"]
            )
            if len(polyline) > 1:
                geometry_source = "step_direction_estimate"
        result = {
            "origin": origin,
            "destination": destination,
            "origin_location": start["location"],
            "destination_location": end["location"],
            "mode": self._transit_mode(transit, railways),
            "duration_minutes": max(1, math.ceil(self._number(transit.get("duration")) / 60)),
            "walking_distance_km": round(
                self._number(transit.get("walking_distance")) / 1000, 2
            ),
            "cost": self._optional_number(transit.get("cost")),
            "transfers": self._transfer_count(transit),
            # Keep the provider's observed geometry so the UI can draw the
            # selected public-transit route instead of a straight endpoint
            # line.  Some MCP deployments omit it, in which case the caller
            # will safely fall back to the endpoint map.
            "polyline": polyline,
            "polyline_source": geometry_source,
            "source": "高德地图 MCP Streamable HTTP",
        }
        if railways:
            # Keep the observed train number/name so the assistant can explain
            # that the public-transit result includes a railway leg instead of
            # presenting it as a generic bus route.
            result["railways"] = railways
        return result

    async def _distance_measure(self, arguments: dict[str, Any]) -> dict[str, Any]:
        origin = self._text(arguments.get("origin"))
        destination = self._text(arguments.get("destination"))
        city = self._text(arguments.get("city"))
        start = await self._resolve_place(origin, city)
        end = await self._resolve_place(destination, city)
        response = self._object(
            await self.client.call_tool(
                "maps_distance",
                {
                    "origins": start["location"],
                    "destination": end["location"],
                    "type": "1",
                },
            ),
            "maps_distance",
        )
        results = response.get("results")
        if not isinstance(results, list) or not results or not isinstance(results[0], dict):
            raise RuntimeError(f"高德 MCP 未返回从 {origin} 到 {destination} 的距离")
        result = results[0]
        return {
            "origin": origin,
            "destination": destination,
            "origin_location": start["location"],
            "destination_location": end["location"],
            "distance_km": round(self._number(result.get("distance")) / 1000, 2),
            "driving_duration_minutes": max(
                1, math.ceil(self._number(result.get("duration")) / 60)
            ),
            "source": "高德地图 MCP Streamable HTTP",
        }

    async def _route_driving(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return await self._point_to_point_route(
            "maps_direction_driving", "驾车", arguments
        )

    async def _route_walking(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return await self._point_to_point_route(
            "maps_direction_walking", "步行", arguments
        )

    async def _point_to_point_route(
        self,
        mcp_tool: str,
        mode: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        origin = self._text(arguments.get("origin"))
        destination = self._text(arguments.get("destination"))
        city = self._text(arguments.get("city"))
        start = await self._resolve_place(origin, city)
        end = await self._resolve_place(destination, city)
        response = self._object(
            await self.client.call_tool(
                mcp_tool,
                {"origin": start["location"], "destination": end["location"]},
            ),
            mcp_tool,
        )
        route = response.get("route")
        route_data = route if isinstance(route, dict) else response
        paths = route_data.get("paths")
        if not isinstance(paths, list) or not paths or not isinstance(paths[0], dict):
            raise RuntimeError(f"高德 MCP 未找到从 {origin} 到 {destination} 的{mode}路线")
        path = paths[0]
        polyline = self._route_polyline(path)
        geometry_source = "provider_geometry" if len(polyline) > 1 else ""
        if len(polyline) < 2:
            # The public Amap MCP response often includes each instruction's
            # orientation and distance but leaves ``path`` empty.  Preserve
            # those verified observations as a non-straight route diagram
            # while making its non-exact nature explicit to the UI.
            polyline = self._estimate_step_polyline(
                path.get("steps"), start["location"], end["location"]
            )
            if len(polyline) > 1:
                geometry_source = "step_direction_estimate"
        return {
            "origin": origin,
            "destination": destination,
            "origin_location": start["location"],
            "destination_location": end["location"],
            "mode": mode,
            "distance_km": round(self._number(path.get("distance")) / 1000, 2),
            "duration_minutes": max(1, math.ceil(self._number(path.get("duration")) / 60)),
            "steps": path.get("steps") if isinstance(path.get("steps"), list) else [],
            "polyline": polyline,
            "polyline_source": geometry_source,
            "source": "高德地图 MCP Streamable HTTP",
        }

    async def _resolve_place(self, place: str, city: str = "") -> dict[str, str]:
        if self._is_location(place):
            return {"location": place, "adcode": "", "city": city}
        if not place:
            raise RuntimeError("地点不能为空")
        cache_key = (place, city)
        if cached := self._geocode_cache.get(cache_key):
            return cached.copy()
        arguments = {"address": place}
        if city:
            arguments["city"] = city
        response = self._object(
            await self.client.call_tool("maps_geo", arguments),
            "maps_geo",
        )
        results = response.get("results")
        if not isinstance(results, list) or not results or not isinstance(results[0], dict):
            raise RuntimeError(f"高德 MCP 未能定位地点：{place}")
        geocode = results[0]
        location = self._text(geocode.get("location"))
        if not self._is_location(location):
            raise RuntimeError(f"高德 MCP 返回的地点坐标无效：{place}")
        result = {
            "location": location,
            "adcode": self._text(geocode.get("adcode")),
            "city": self._text(geocode.get("city")) or city,
        }
        self._geocode_cache[cache_key] = result
        return result.copy()

    @classmethod
    def _route_polyline(cls, value: Any) -> list[str]:
        """Extract an Amap route geometry as ordered ``lng,lat`` points.

        Driving/walking responses usually put ``polyline`` on each step;
        transit responses nest it under walking and bus-line segments.  The
        MCP variants differ slightly, so walk only geometry-like fields and
        normalize all of them to one compact representation for the client.
        """

        points: list[str] = []

        def add_text(raw: Any) -> None:
            if not isinstance(raw, str):
                return
            for token in re.split(r"[;|\s]+", raw.strip()):
                values = token.split(",")
                if len(values) != 2:
                    continue
                try:
                    longitude, latitude = float(values[0]), float(values[1])
                except (TypeError, ValueError):
                    continue
                if not (-180 <= longitude <= 180 and -90 <= latitude <= 90):
                    continue
                point = f"{longitude},{latitude}"
                if not points or points[-1] != point:
                    points.append(point)

        def walk(item: Any, geometry_only: bool = False) -> None:
            if isinstance(item, str):
                if geometry_only:
                    add_text(item)
                return
            if isinstance(item, list):
                if (
                    len(item) >= 2
                    and not isinstance(item[0], (dict, list))
                    and not isinstance(item[1], (dict, list))
                ):
                    add_text(f"{item[0]},{item[1]}")
                    return
                for nested in item:
                    walk(nested, geometry_only)
                return
            if not isinstance(item, dict):
                return
            if geometry_only and ("lng" in item or "longitude" in item) and ("lat" in item or "latitude" in item):
                add_text(f"{item.get('lng', item.get('longitude'))},{item.get('lat', item.get('latitude'))}")
                return
            for key, nested in item.items():
                key_name = str(key).lower()
                if key_name in {"polyline", "geometry", "route_path", "path"}:
                    walk(nested, True)
                elif key_name in {"steps", "segments", "walking", "bus", "buslines", "railway", "transits"}:
                    walk(nested, geometry_only)

        walk(value)
        return points[:2000]

    @classmethod
    def _transit_step_polyline(
        cls, transit: dict[str, Any], origin: str, destination: str
    ) -> list[str]:
        """Build a route-shaped diagram from transit legs when geometry is absent.

        Transit MCP payloads differ widely.  Walking legs may include full
        steps, while bus/rail legs often expose only stop names.  We use any
        verified coordinates and walking step observations that are present;
        returning an empty list is safer than drawing a misleading endpoint
        line when there is no usable intermediate observation.
        """

        segments = transit.get("segments")
        if not isinstance(segments, list):
            return []
        steps: list[dict[str, Any]] = []
        anchors: list[str] = []
        for segment in segments:
            if not isinstance(segment, dict):
                continue
            walking = segment.get("walking")
            if not isinstance(walking, dict):
                continue
            for key in ("origin", "start", "departure"):
                location = cls._text(walking.get(key))
                if cls._is_location(location):
                    anchors.append(location)
                    break
            nested = walking.get("steps")
            if isinstance(nested, list):
                steps.extend(item for item in nested if isinstance(item, dict))
            for key in ("destination", "end", "arrival"):
                location = cls._text(walking.get(key))
                if cls._is_location(location):
                    anchors.append(location)
                    break
        estimated = cls._estimate_step_polyline(steps, origin, destination)
        if len(estimated) > 1:
            return estimated
        # If there are no directional walking steps, retain only explicitly
        # supplied walking anchors; do not connect them with a straight line.
        values = [origin, *anchors, destination]
        result: list[str] = []
        for value in values:
            if cls._is_location(value) and (not result or result[-1] != value):
                result.append(value)
        return result if len(result) > 2 else []

    @classmethod
    def _estimate_step_polyline(
        cls, steps: Any, origin: str, destination: str
    ) -> list[str]:
        """Estimate intermediate coordinates from observed direction/distance.

        This is a visual aid, not navigation geometry.  Each point is derived
        from the MCP's own step distance and compass direction, then a smooth
        endpoint correction keeps the verified origin/destination fixed.  The
        caller exposes ``polyline_source=step_direction_estimate`` so clients
        can show the appropriate disclaimer.
        """

        if not isinstance(steps, list) or not cls._is_location(origin) or not cls._is_location(destination):
            return []
        try:
            origin_lng, origin_lat = (float(value) for value in origin.split(","))
            destination_lng, destination_lat = (float(value) for value in destination.split(","))
        except (TypeError, ValueError):
            return []
        radius = 6_378_137.0
        cos_lat = max(0.2, math.cos(math.radians(origin_lat)))
        meters_per_degree_lat = math.pi * radius / 180.0
        meters_per_degree_lng = meters_per_degree_lat * cos_lat
        raw: list[tuple[float, float]] = [(0.0, 0.0)]
        for step in steps:
            if not isinstance(step, dict):
                continue
            distance = cls._step_distance(step.get("distance"))
            if distance <= 0:
                continue
            direction = cls._step_bearing(step)
            if direction is None:
                continue
            previous_x, previous_y = raw[-1]
            angle = math.radians(direction)
            # Bearing is clockwise from north: x=east, y=north.
            raw.append((
                previous_x + math.sin(angle) * distance,
                previous_y + math.cos(angle) * distance,
            ))
        if len(raw) < 3:
            return []
        target_x = (destination_lng - origin_lng) * meters_per_degree_lng
        target_y = (destination_lat - origin_lat) * meters_per_degree_lat
        end_x, end_y = raw[-1]
        points: list[str] = []
        for index, (x, y) in enumerate(raw):
            fraction = index / (len(raw) - 1)
            adjusted_x = x + (target_x - end_x) * fraction
            adjusted_y = y + (target_y - end_y) * fraction
            lng = origin_lng + adjusted_x / meters_per_degree_lng
            lat = origin_lat + adjusted_y / meters_per_degree_lat
            point = f"{lng:.6f},{lat:.6f}"
            if not points or points[-1] != point:
                points.append(point)
        # The endpoints are independently verified coordinates; never let
        # rounding move them away from the POIs used by the map markers.
        if points:
            points[0] = f"{origin_lng},{origin_lat}"
            points[-1] = f"{destination_lng},{destination_lat}"
        return points[:2000]

    @classmethod
    def _step_bearing(cls, step: dict[str, Any]) -> float | None:
        text = " ".join(
            cls._text(step.get(key)) for key in ("orientation", "direction", "instruction")
        )
        # Prefer compound compass directions before their one-character
        # components (e.g. 东北 must not be parsed as 东).
        match = re.search(r"(东北|东南|西北|西南|北|南|东|西)", text)
        if not match:
            return None
        return {
            "北": 0.0,
            "东北": 45.0,
            "东": 90.0,
            "东南": 135.0,
            "南": 180.0,
            "西南": 225.0,
            "西": 270.0,
            "西北": 315.0,
        }[match.group(1)]

    @staticmethod
    def _object(value: Any, tool_name: str) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise RuntimeError(f"高德 MCP 工具 {tool_name} 返回格式错误")  # noqa: TRY004
        return value

    @staticmethod
    def _text(value: Any) -> str:
        return value.strip() if isinstance(value, str) else ""

    @classmethod
    def _photo_url(cls, value: Any) -> str:
        """Extract one usable image URL from the varied Amap POI shapes.

        Depending on the MCP server/API version, POI images may be exposed as
        ``photo`` (a string), ``photos`` (a list of strings) or a list of
        objects containing ``url``/``image_url``.  Keep only the first URL so
        the result remains compact and safe to pass to the UI/LLM.
        """
        urls = cls._photo_urls(value, limit=1)
        return urls[0] if urls else ""

    @classmethod
    def _photo_urls(cls, value: Any, limit: int = MAX_POI_PHOTOS) -> list[str]:
        """Extract at most ``limit`` unique, safe image URLs."""
        if limit <= 0:
            return []
        if isinstance(value, str):
            # Amap may return several CDN URLs in one pipe-delimited field.
            # Preserve each original URL so the UI can choose two sharp
            # images instead of rendering a combined/invalid thumbnail URL.
            candidates = [
                item.strip() for item in re.split(r"[|,]", value) if item.strip()
            ]
            urls: list[str] = []
            identities: set[str] = set()
            for candidate in candidates:
                if candidate.startswith("//"):
                    candidate = f"https:{candidate}"
                if not candidate.startswith(("https://", "http://")):
                    continue
                if candidate.startswith("http://") and any(
                    host in candidate for host in ("amap.com", "autonavi.com")
                ):
                    candidate = "https://" + candidate[len("http://"):]
                identity = cls._photo_identity(candidate)
                if identity and identity not in identities:
                    urls.append(candidate)
                    identities.add(identity)
                if len(urls) >= limit:
                    break
            return urls
        if isinstance(value, dict):
            # Prefer original/large variants when an MCP server supplies
            # multiple renditions; thumbnail fields are deliberately last.
            for key in (
                "original_url", "original", "large_url", "large", "url",
                "image_url", "photo_url", "src", "image", "thumbnail",
                "imgurl", "img_url", "picurl", "pic_url", "imageUrl", "photoUrl",
            ):
                urls = cls._photo_urls(value.get(key), limit)
                if urls:
                    return urls
            return []
        if not isinstance(value, list):
            return []
        urls: list[str] = []
        identities: set[str] = set()
        for item in value:
            for url in cls._photo_urls(item, limit):
                identity = cls._photo_identity(url)
                if identity and identity not in identities:
                    urls.append(url)
                    identities.add(identity)
                if len(urls) >= limit:
                    return urls
        return urls

    @staticmethod
    def _photo_identity(url: str) -> str:
        """Return a stable identity for duplicate CDN renditions.

        Image CDNs commonly append crop/size/query parameters to the same
        source image. Those variants should count as one photo; retain the
        first URL so the provider's preferred rendition is still rendered.
        """
        try:
            parsed = urlsplit(url)
            if not parsed.netloc or not parsed.path:
                return ""
            path = unquote(parsed.path).rstrip("/") or "/"
            return f"{parsed.netloc.lower()}{path}"
        except (TypeError, ValueError):
            return url.lower().split("?", 1)[0].split("#", 1)[0].rstrip("/")

    @staticmethod
    def _number(value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _step_distance(value: Any) -> float:
        """Parse a step distance without changing route duration semantics."""

        try:
            return float(value)
        except (TypeError, ValueError):
            match = re.search(r"[-+]?\d+(?:\.\d+)?", str(value or ""))
            return float(match.group(0)) if match else 0.0

    @classmethod
    def _optional_number(cls, value: Any) -> float | None:
        text = cls._text(value)
        return cls._number(text) if text else None

    @staticmethod
    def _is_location(value: str) -> bool:
        try:
            longitude, latitude = (float(item) for item in value.split(","))
        except (TypeError, ValueError):
            return False
        return -180 <= longitude <= 180 and -90 <= latitude <= 90

    @staticmethod
    def _transfer_count(transit: dict[str, Any]) -> int:
        segments = transit.get("segments")
        if not isinstance(segments, list):
            return 0
        bus_segments = 0
        for segment in segments:
            if not isinstance(segment, dict):
                continue
            bus = segment.get("bus")
            buslines = bus.get("buslines") if isinstance(bus, dict) else None
            if isinstance(buslines, list) and buslines:
                bus_segments += 1
        return max(0, bus_segments - 1)

    @classmethod
    def _railway_details(cls, transit: dict[str, Any]) -> list[dict[str, str]]:
        """Extract the railway legs returned by maps_direction_transit_integrated."""
        segments = transit.get("segments")
        if not isinstance(segments, list):
            return []
        railways: list[dict[str, str]] = []
        for segment in segments:
            if not isinstance(segment, dict):
                continue
            railway = segment.get("railway")
            if not isinstance(railway, dict):
                continue
            name = cls._text(railway.get("name"))
            trip = cls._text(railway.get("trip"))
            if name or trip:
                railways.append({"name": name, "trip": trip})
        return railways

    @classmethod
    def _transit_mode(
        cls, transit: dict[str, Any], railways: list[dict[str, str]]
    ) -> str:
        if not railways:
            return "公交/地铁"
        labels: list[str] = []
        for railway in railways:
            code = (railway.get("trip") or railway.get("name") or "").upper()
            label = (
                "高铁"
                if re.match(r"^G\d", code)
                else "动车"
                if re.match(r"^D\d", code)
                else "城际"
                if re.match(r"^C\d", code)
                else "火车"
            )
            if label not in labels:
                labels.append(label)
        railway_label = "/".join(labels) or "铁路"
        has_bus = False
        segments = transit.get("segments")
        if isinstance(segments, list):
            has_bus = any(
                isinstance(segment, dict)
                and isinstance(segment.get("bus"), dict)
                and isinstance(segment["bus"].get("buslines"), list)
                and bool(segment["bus"]["buslines"])
                for segment in segments
            )
        return f"{railway_label} + 公交/地铁" if has_bus else railway_label
