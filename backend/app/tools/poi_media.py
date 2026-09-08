"""POI 图片与回答实体补全工具。

图片是地图/POI 观测的展示层数据，不应由行程 Agent 自己维护解析细节。
本工具负责统一图片字段、识别回答中提到的景点，并通过已注入的高德工具
补齐可核验的图片；拿不到可靠图片时保持为空，不生成占位或错误图片。
"""

import asyncio
import re
from typing import Any
from urllib.parse import urlsplit

from backend.app.tools.amap import AmapMcpTool
from backend.app.tools.itinerary_map import ItineraryMapTool
from backend.app.tools.models import EvidenceItem

MAX_POI_PHOTOS = 2


class PoiMediaTool:
    """Agent 可调用的景点图片标准化与补全工具。"""

    name = "poi_media"

    @staticmethod
    def _image_key(value: str) -> str:
        try:
            parsed = urlsplit(value)
            return f"{parsed.netloc.lower()}{parsed.path.rstrip('/')}" or value.lower()
        except (TypeError, ValueError):
            return value.lower().split("?", 1)[0].split("#", 1)[0].rstrip("/")

    def __init__(
        self,
        amap_tool: AmapMcpTool,
        map_tool: ItineraryMapTool | None = None,
    ) -> None:
        self.amap_tool = amap_tool
        self.map_tool = map_tool or ItineraryMapTool()

    @staticmethod
    def poi_display_name(place: dict[str, Any]) -> str:
        """Return a concise provider-grounded label without changing identity.

        Map providers occasionally expose an internal hierarchy such as
        ``杭州西湖风景名胜区-白堤-某打卡点``.  The complete provider ``name``
        remains untouched for exact image/location matching, while cards,
        day plans and map labels can use this stable display-only value.
        """

        raw = re.sub(r"\s+", " ", str(place.get("name") or "")).strip()
        if not raw:
            return ""
        value = re.sub(
            r"[（(][^）)]*(?:打卡|游船|路线|线路|推荐|营销|内部|入口|观光)[^）)]*[）)]",
            "",
            raw,
        ).strip()
        # Some provider/model labels prefix a real name with only its generic
        # category (``湿地公园·长广溪国家湿地公园``). Keep the named entity on
        # the right; do not split official compound names such as
        # ``天一阁·月湖景区`` whose left side is not a generic category.
        generic_prefix = re.match(
            r"^(?:景点|景区|公园|湿地公园|国家公园|主题乐园|古镇|博物馆|"
            r"历史文化|自然风光|湖光山色)[·：:]\s*(.+)$",
            value,
        )
        if generic_prefix:
            value = generic_prefix.group(1).strip()
        parts = [part.strip() for part in re.split(r"\s*[-—–]\s*", value) if part.strip()]
        if len(parts) > 1 and re.search(
            r"(?:风景名胜区|旅游景区|风景区|景区|博物院|博物馆|公园|古镇|遗址)$",
            parts[0],
        ):
            value = parts[0]
        city = str(place.get("city") or "").strip().removesuffix("市")
        if city and value.startswith(city) and len(value) > len(city) + 1:
            value = value[len(city) :].strip()
        return value.strip(" ，,。；;、") or raw

    @classmethod
    def normalise_poi_media(cls, places: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Normalize provider ``photo/photos`` variants to at most two URLs."""

        def urls(value: Any) -> list[str]:
            if isinstance(value, str):
                return [
                    candidate.strip()
                    for candidate in re.split(r"[|,]", value)
                    if candidate.strip().startswith(("https://", "http://"))
                ]
            if isinstance(value, dict):
                result: list[str] = []
                for key in (
                    "original_url", "original", "large_url", "large", "url",
                    "image_url", "photo_url", "src", "image", "thumbnail",
                    "imgurl", "img_url", "picurl", "pic_url", "imageUrl", "photoUrl",
                ):
                    result.extend(urls(value.get(key)))
                return result
            if isinstance(value, list):
                result: list[str] = []
                for item in value:
                    result.extend(urls(item))
                return result
            return []

        normalized: list[dict[str, Any]] = []
        for place in places:
            if not isinstance(place, dict):
                continue
            item = dict(place)
            candidates = urls(item.get("photos")) + urls(item.get("photo"))
            unique: list[str] = []
            identities: set[str] = set()
            for candidate in candidates:
                identity = cls._image_key(candidate)
                if identity and identity not in identities:
                    unique.append(candidate)
                    identities.add(identity)
                if len(unique) >= MAX_POI_PHOTOS:
                    break
            if unique:
                item["photo"] = unique[0]
                item["photos"] = unique[:MAX_POI_PHOTOS]
            else:
                item.pop("photo", None)
                item.pop("photos", None)
            normalized.append(item)
        return normalized

    @classmethod
    def attach_evidence_images(
        cls,
        places: list[dict[str, Any]],
        evidence: list[EvidenceItem],
        *,
        destination: str = "",
    ) -> list[dict[str, Any]]:
        """Attach strictly name-matched images extracted from web pages.

        Search pages now carry ``metadata.images`` from their HTML.  An image
        is eligible only when its alt/title/filename or the page title names
        the same POI; a city-wide page with an unrelated hero image therefore
        cannot become a photo for every attraction.  Amap/Commons photos stay
        first, and web evidence only fills the remaining one or two slots.
        """

        if not places or not evidence:
            return places

        def image_key(value: str) -> str:
            try:
                parsed = urlsplit(value)
                return f"{parsed.netloc.lower()}{parsed.path.rstrip('/')}" or value.lower()
            except (TypeError, ValueError):
                return value.lower().split("?", 1)[0].split("#", 1)[0].rstrip("/")

        def text(value: Any) -> str:
            return re.sub(r"[^\w\u4e00-\u9fff]+", "", str(value or "").lower())

        def aliases(place: dict[str, Any]) -> list[str]:
            values = [
                str(place.get("name") or "").strip(),
                cls.poi_display_name(place),
                str(place.get("display_name") or "").strip(),
            ]
            values.extend(
                part.strip()
                for part in re.split(r"[，,、/|]", str(place.get("alias") or ""))
                if part.strip()
            )
            # Amap sometimes appends 景区/风景区 to an otherwise exact name.
            expanded: set[str] = set(values)
            for value in values:
                for suffix in ("风景名胜区", "旅游景区", "风景区", "景区"):
                    if value.endswith(suffix) and len(value) > len(suffix) + 1:
                        expanded.add(value[: -len(suffix)])
            return sorted((item for item in expanded if len(text(item)) >= 2), key=len, reverse=True)

        place_aliases = [aliases(place) for place in places if isinstance(place, dict)]

        def image_values(metadata: dict[str, Any]) -> list[dict[str, str]]:
            raw = metadata.get("images")
            if isinstance(raw, list):
                values = raw
            elif isinstance(raw, (str, dict)):
                values = [raw]
            else:
                values = []
            output: list[dict[str, str]] = []
            for value in values:
                if isinstance(value, str):
                    url = value.strip()
                    item = {"url": url, "alt": "", "title": ""}
                elif isinstance(value, dict):
                    url = str(value.get("url") or value.get("image_url") or "").strip()
                    item = {
                        "url": url,
                        "alt": str(value.get("alt") or value.get("title") or value.get("caption") or "").strip(),
                        "title": str(value.get("title") or "").strip(),
                    }
                else:
                    continue
                if url.startswith(("https://", "http://")) and image_key(url) not in {image_key(item["url"]) for item in output}:
                    output.append(item)
            return output

        enriched: list[dict[str, Any]] = []
        for place in places:
            if not isinstance(place, dict):
                continue
            item = dict(place)
            if cls.is_supporting_poi(item):
                enriched.append(item)
                continue
            existing = cls.normalise_poi_media([item])[0]
            urls = list(existing.get("photos") or [])
            poi_aliases = aliases(item)
            if not poi_aliases:
                enriched.append(existing)
                continue
            scored: list[tuple[int, str]] = []
            for source in evidence:
                metadata = source.metadata if isinstance(source.metadata, dict) else {}
                page_text = text(f"{source.title} {source.content}")
                title_text = text(source.title)
                title_poi_count = sum(
                    1 for candidate_aliases in place_aliases
                    if any(text(alias) in title_text for alias in candidate_aliases)
                )
                for image in image_values(metadata):
                    image_url = image["url"]
                    image_meta = text(f"{image.get('alt')} {image.get('title')}")
                    image_text = text(f"{image_meta} {image_url}")
                    score = 0
                    name_in_image = False
                    name_in_title = False
                    for alias in poi_aliases:
                        needle = text(alias)
                        if not needle:
                            continue
                        if needle in image_text:
                            name_in_image = True
                            score = max(score, 10 + min(len(needle), 12))
                        if needle in text(source.title):
                            name_in_title = True
                            score = max(score, 7 + min(len(needle), 12))
                        if needle in page_text:
                            score = max(score, 3 + min(len(needle), 8))
                    if destination and text(destination) in page_text:
                        score += 1
                    # A page titled “龙门石窟攻略” may contain a related
                    # widget whose alt says “北京天安门”.  Do not let that
                    # explicit competing landmark inherit the page title;
                    # an empty/generic alt is still allowed for a hero image.
                    generic_alt = {
                        "旅游风光", "景区图片", "景点图片", "风景照片", "旅游照片", "景区风光",
                    }
                    if name_in_title and image_meta and not name_in_image and image_meta not in generic_alt:
                        continue
                    # A combined “天一阁·月湖景区” article often exposes one
                    # collage as its OG image. Do not attach that same generic
                    # image to every POI; only an explicitly named image can
                    # disambiguate a multi-attraction page.
                    if name_in_title and not name_in_image and title_poi_count > 1:
                        continue
                    # Bare images from a generic city page are not safe: they
                    # lack a POI name in both image metadata and page title.
                    if score >= 9 and (name_in_image or name_in_title):
                        scored.append((score, image_url))
            for _, image_url in sorted(scored, key=lambda pair: (-pair[0], pair[1])):
                if image_key(image_url) not in {image_key(value) for value in urls}:
                    urls.append(image_url)
                if len(urls) >= MAX_POI_PHOTOS:
                    break
            if urls:
                existing["photos"] = urls[:MAX_POI_PHOTOS]
                existing["photo"] = urls[0]
            enriched.append(existing)
        return enriched

    @classmethod
    def extract_answer_landmarks(cls, text: str) -> list[str]:
        """Extract introduced landmark headings without swallowing prose.

        Structured headings (day routes, ``上午：景点`` and bold labels) are
        authoritative. Free-prose extraction is only a fallback; otherwise a
        sentence such as ``故宫位于景山前街`` can be mistaken for one long POI
        name and consume the resolution budget before real attractions.
        """

        raw_text = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
        if not raw_text.strip():
            return []
        suffix = (
            r"(?:风景名胜区|旅游景区|旅游区|风景区|国家公园|湿地公园|博物院|博物馆|"
            r"纪念馆|步行街|商业街|街区|古城|城墙|陵园|寺院|岛屿|景区|湿地|公园|"
            r"石窟|古镇|故居|遗址|广场|牌坊|天街|瀑布|渡口|残雪|寺|塔|湖|岛|湾|"
            r"滩|山|峰|洞|桥|堤|街|阁|楼|台|宫|馆|港|村|庙|祠|殿|陵)"
        )
        candidates: list[str] = []

        # These are prose connectors, not part of a place name. A previous
        # implementation accepted any heading that merely contained “湖” or
        # “古镇”, turning phrases such as “从太湖山水” and “古镇历史” into
        # geocoding requests and fake POI cards.
        relation_prefix = re.compile(
            r"^(?:从|由|到|前往|位于|坐落于?|紧邻|毗邻|邻近|靠近|周边|附近|这里|"
            r"景点类型|方便|推荐|适合|可以|无锡的|杭州的|南京的|北京的)"
        )

        def add(raw: str) -> None:
            value = re.sub(r"^[\s\-*•#]+", "", str(raw or ""))
            # Labels in a structured answer are safe to remove; the text
            # after “推荐：” or “景点介绍：” may still be a real landmark.
            value = re.sub(
                r"^(?:推荐|建议|景点(?:介绍)?|游玩建议)\s*[：:]\s*",
                "",
                value,
            )
            if relation_prefix.match(value):
                return
            value = re.sub(r"^(?:day\s*\d+|第\s*\d+\s*天)[^：:]*[：:]\s*", "", value, flags=re.I)
            value = re.sub(
                r"^(?:上午|中午|下午|晚上|早上|顺路|备选|推荐|建议)\s*[：:]\s*",
                "",
                value,
            )
            value = re.split(
                r"(?:游览|参观|前往|安排|推荐|打卡|了解|前去|经过|抵达|来到|体验|感受|"
                r"包括|进入|转入)\s*",
                value,
            )[-1]
            # Keep the final landmark token if the model includes a city or
            # filler verb in the same heading (e.g. “宁波看天一阁”).
            value = re.split(
                r"(?:我想(?:去|问)?|我问|请问|帮我(?:找|查|介绍)|看看|看|有|是|去|到|前往|查询|搜索)\s*",
                value,
            )[-1]
            tail = re.search(rf"([\u4e00-\u9fff]{{1,20}}{suffix})$", value)
            # A candidate must end in a known landmark suffix. Merely
            # containing one (e.g. “湖光山色” or “古镇历史”) is descriptive
            # prose and must not be sent to Amap for resolution.
            if not tail:
                return
            value = tail.group(1)
            value = value.strip(" 和与及，,。；;、：:（）()[]【】*")
            if not value or len(value) > 32 or value in {"天气提醒", "住宿建议", "市区自由活动"}:
                return
            if value not in candidates:
                candidates.append(value)

        for raw in re.findall(r"\*\*([^*\n]{2,40})\*\*", raw_text):
            for part in re.split(r"[、，,+]|和|与|及", raw):
                add(part)
        for line in raw_text.split("\n"):
            line = re.sub(r"^[\s\-*•#]+", "", line).strip()
            if not line:
                continue
            day_match = re.match(
                r"^(?:day\s*\d+|第\s*\d+\s*天)[^：:]*[：:]\s*(.+)$",
                line,
                flags=re.I,
            )
            if day_match:
                for part in re.split(r"\s*(?:→|➡|->|—>|、|，|,|\+|和|与|及)\s*", day_match.group(1)):
                    add(re.split(r"[（(]", part, maxsplit=1)[0])
            time_match = re.match(
                r"^(?:上午|中午|下午|晚上|早上|顺路|备选|推荐|建议)\s*[：:]\s*([^，。；（(]{2,40})",
                line,
            )
            if time_match:
                for part in re.split(r"\s*(?:→|➡|->|—>|、|和|与|及)\s*", time_match.group(1)):
                    add(part)

        if candidates:
            return candidates[:12]

        # Unformatted answers still commonly use ``西湖适合……，灵隐寺位于……``.
        # Keep only the subject before an explanatory predicate, rather than
        # scanning an arbitrary 20-character Chinese window ending in “街/殿”.
        compact = " ".join(raw_text.split())
        for clause in re.split(r"[，,。；;！？!?]", compact):
            subject = re.split(
                r"(?:位于|坐落于?|始建于?|建于|创建于?|是|以.+?著称|拥有|适合|作为)",
                clause,
                maxsplit=1,
            )[0]
            for part in re.split(r"\s*(?:→|➡|->|—>|、|和|与|及)\s*", subject):
                add(part)
        return candidates[:12]

    @staticmethod
    def is_supporting_poi(item: dict[str, Any]) -> bool:
        facility_terms = (
            "售票处", "补票处", "服务区", "游客中心", "游客服务中心", "公交站", "停车场",
            "票务中心", "检票口", "讲解服务", "购物中心", "宾馆", "酒店", "民宿",
            "客栈", "旅馆", "住宿", "青年旅舍", "餐厅", "码头",
        )
        return any(term in str(item.get("name") or "") for term in facility_terms)

    @classmethod
    def remove_supporting_pois(
        cls, places: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Remove facilities from itinerary activities while preserving a
        transparent fallback when the provider returned facilities only.
        """
        scenic = [item for item in places if not cls.is_supporting_poi(item)]
        return scenic or places

    @classmethod
    def attach_poi_descriptions(
        cls, places: list[dict[str, Any]], evidence: list[EvidenceItem]
    ) -> list[dict[str, Any]]:
        """Attach one grounded, attraction-specific description per POI.

        Navigation sentences are deliberately rejected even when they also
        contain words such as “景色” or “适合”. A description already used for
        another POI is not reused, preventing identical image-card copy.
        """
        if not places:
            return places
        intro_terms = re.compile(
            r"位于|坐落|特色|闻名|著称|历史|始建|建于|景观|建筑|文化|山水|湖光|"
            r"适合|推荐|值得|参观|游览|开放|门票|面积|保存|世界遗产|街区|商业街"
        )
        route_terms = re.compile(
            r"路线|交通方式|起点|终点|导航|换乘|公交|地铁|驾车|打车|乘坐|车站|"
            r"站点|公里|分钟|耗时|直达|从.{1,16}(?:到|至).{1,16}|.{1,16}(?:→|➡).{1,16}"
        )
        schedule_terms = re.compile(
            r"(?:上午|中午|下午|晚上|早上|傍晚|清晨).{0,18}"
            r"(?:安排|留给|前往|步行|乘坐|搭乘|驾车|打车|抵达|游览|参观|时间)"
            r"|(?:步行|乘坐|搭乘|驾车|打车|骑行).{0,12}(?:到|前往|抵达)"
        )
        address_pattern = re.compile(r"(?:路|街|巷|道|大道|弄)\s*\d+\s*号?")

        def aliases(poi: dict[str, Any]) -> list[str]:
            values = [
                str(poi.get("name") or "").strip(),
                cls.poi_display_name(poi),
                str(poi.get("display_name") or "").strip(),
                str(poi.get("alias") or "").strip(),
            ]
            values.extend(
                part.strip()
                for part in re.split(r"[，,、/|]", str(poi.get("alias") or ""))
                if part.strip()
            )
            return sorted(
                {value for value in values if len(value) >= 2},
                key=len,
                reverse=True,
            )

        all_terms = {term for place in places for term in aliases(place)}

        def best_description(poi: dict[str, Any], used: set[str]) -> str:
            terms = aliases(poi)
            if not terms:
                return ""
            candidates: list[tuple[float, str]] = []
            for item in evidence:
                content = str(getattr(item, "content", "") or "")
                for raw in re.split(r"(?<=[。！？；])|\n", content):
                    sentence = re.sub(r"\s+", " ", raw).strip(" -•")
                    # Short factual introductions (for example “灵隐寺始建
                    # 于东晋，是杭州古刹”) are still useful.  The previous
                    # 18-character floor silently discarded these common
                    # descriptions and left the card with only a name.
                    if len(sentence) < 10 or not any(term in sentence for term in terms):
                        continue
                    # A schedule sentence can mention a POI only as an
                    # address, e.g. “下午把时间留给中国科举博物馆（贡院街95号）”.
                    # It belongs to the itinerary prose, not to 贡院街's own
                    # introduction. Reject it before scoring semantic terms.
                    if route_terms.search(sentence) or schedule_terms.search(sentence):
                        continue
                    if address_pattern.search(sentence) and not intro_terms.search(sentence):
                        continue
                    other_names = [
                        other
                        for other in all_terms
                        if other not in terms
                        and other in sentence
                        # A provider may return both “西湖” and
                        # “西湖风景名胜区”.  The longer form is a naming
                        # variant, not a different attraction, so it should
                        # not make an otherwise correct sentence unusable.
                        and not any(
                            term in other or other in term for term in terms
                        )
                    ]
                    candidate_sentences = [sentence]
                    # A paragraph can put two attractions in one long
                    # sentence separated by commas.  Keep only the clause
                    # naming this POI instead of assigning the neighbour's
                    # introduction to it.
                    if other_names:
                        candidate_sentences = [
                            part.strip(" ，,；;")
                            for part in re.split(r"[，,；;]", sentence)
                            if any(term in part for term in terms)
                        ]
                    for candidate_sentence in candidate_sentences:
                        if len(candidate_sentence) < 10 or any(
                            other in candidate_sentence for other in other_names
                        ):
                            continue
                        candidate_key = re.sub(r"\s+", "", candidate_sentence)
                        if candidate_key in used:
                            continue
                        exact = max(
                            (len(term) for term in terms if term in candidate_sentence),
                            default=0,
                        )
                        score = (
                            (3 if intro_terms.search(candidate_sentence) else 0)
                            + exact / 20
                        )
                        candidates.append((score, candidate_sentence))
            if not candidates:
                return ""
            candidates.sort(key=lambda pair: (pair[0], len(pair[1])), reverse=True)
            # Keep up to two independently grounded sentences.  One sentence
            # often only states a location while the next gives the landmark's
            # history or best visiting time; combining them makes the
            # introduction useful without asking the model to invent details.
            selected: list[str] = []
            selected_keys: set[str] = set()
            for _, sentence in candidates:
                key = re.sub(r"\s+", "", sentence)
                if key in selected_keys:
                    continue
                if any(sentence in existing or existing in sentence for existing in selected):
                    continue
                selected.append(sentence)
                selected_keys.add(key)
                if len(selected) >= 2:
                    break
            description = " ".join(selected)
            return description[:297] + "…" if len(description) > 300 else description

        enriched: list[dict[str, Any]] = []
        used_descriptions: set[str] = set()
        for place in places:
            if not isinstance(place, dict):
                continue
            item = dict(place)
            if cls.is_supporting_poi(item):
                enriched.append(item)
                continue
            existing = str(item.get("description") or "").strip()
            existing_key = re.sub(r"\s+", "", existing)
            existing_valid = (
                len(existing) >= 18
                and any(term in existing for term in aliases(item))
                and not route_terms.search(existing)
                and not schedule_terms.search(existing)
                and not (
                    address_pattern.search(existing)
                    and not intro_terms.search(existing)
                )
                and existing_key not in used_descriptions
            )
            if existing_valid:
                used_descriptions.add(existing_key)
            else:
                description = best_description(item, used_descriptions)
                if description:
                    item["description"] = description
                    used_descriptions.add(re.sub(r"\s+", "", description))
                elif existing and (
                    route_terms.search(existing)
                    or schedule_terms.search(existing)
                    or existing_key in used_descriptions
                ):
                    item.pop("description", None)
            enriched.append(item)
        return enriched

    @classmethod
    def attach_answer_descriptions(
        cls, places: list[dict[str, Any]], answer: str
    ) -> list[dict[str, Any]]:
        """Map explicitly labelled model prose back to its matching POI.

        Models often format an answer as ``西湖：……`` or put the landmark on
        one line followed by its introduction on the next.  This parser only
        accepts text that names exactly one known POI (or immediately follows
        that POI heading), rejects navigation/schedule prose, and never
        overwrites an already grounded description.  It is therefore a
        presentation bridge rather than a second source of facts.
        """
        if not places or not str(answer or "").strip():
            return places
        route_terms = re.compile(
            r"路线|交通方式|起点|终点|导航|换乘|公交|地铁|驾车|打车|乘坐|车站|"
            r"站点|公里|分钟|耗时|直达|从.{1,16}(?:到|至).{1,16}|.{1,16}(?:→|➡).{1,16}"
        )
        schedule_terms = re.compile(
            r"(?:上午|中午|下午|晚上|早上|傍晚|清晨).{0,18}"
            r"(?:安排|留给|前往|步行|乘坐|搭乘|驾车|打车|抵达|游览|参观|时间)"
            r"|(?:步行|乘坐|搭乘|驾车|打车|骑行).{0,12}(?:到|前往|抵达)"
        )

        def clean_line(value: str) -> str:
            value = re.sub(
                r"\*\*(.+?)\*\*|__(.+?)__",
                lambda match: match.group(1) or match.group(2),
                value,
            )
            value = re.sub(r"^\s*(?:[-*•]|\d+[.)、])\s*", "", value)
            return value.strip(" \t#：:，,。；;、")

        aliases_by_index: dict[int, list[str]] = {}
        for index, place in enumerate(places):
            if not isinstance(place, dict):
                continue
            name = str(place.get("name") or "").strip()
            if name:
                aliases_by_index[index] = sorted(
                    {name, cls.poi_display_name(place), str(place.get("display_name") or "").strip(), *[
                        part.strip()
                        for part in re.split(r"[，,、/|]", str(place.get("alias") or ""))
                        if len(part.strip()) >= 2
                    ]} - {""},
                    key=len,
                    reverse=True,
                )

        extracted: dict[int, list[str]] = {}
        current: int | None = None
        for raw_line in str(answer).replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            line = clean_line(raw_line)
            if not line:
                continue
            if re.match(r"^第\s*\d+\s*天(?:\s*[：:].*)?$", line):
                current = None
                continue
            matches = [
                index
                for index, aliases in aliases_by_index.items()
                if any(alias and alias in line for alias in aliases)
            ]
            if len(matches) == 1:
                index = matches[0]
                aliases = aliases_by_index[index]
                remainder = line
                # Prefer the text after a colon; otherwise remove the POI
                # name and keep a sentence such as “西湖是杭州的……”。
                if re.search(r"[：:]", remainder):
                    remainder = re.split(r"[：:]", remainder, maxsplit=1)[1]
                else:
                    for alias in aliases:
                        remainder = remainder.replace(alias, "", 1)
                        break
                remainder = remainder.strip(" \t-—：:，,。；;")
                current = index
                if len(remainder) >= 10 and not route_terms.search(remainder) and not schedule_terms.search(remainder):
                    extracted.setdefault(index, []).append(remainder)
                continue
            # A continuation line is accepted only after an unambiguous POI
            # heading.  Do not carry context across generic paragraphs.
            if current is None or len(line) < 10 or route_terms.search(line) or schedule_terms.search(line):
                continue
            extracted.setdefault(current, []).append(line)

        enriched: list[dict[str, Any]] = []
        used: set[str] = set()
        for index, place in enumerate(places):
            if not isinstance(place, dict):
                continue
            item = dict(place)
            existing = str(item.get("description") or "").strip()
            if existing:
                used.add(re.sub(r"\s+", "", existing))
            if not existing and extracted.get(index):
                description = " ".join(extracted[index][:2]).strip()
                key = re.sub(r"\s+", "", description)
                if key and key not in used:
                    item["description"] = description[:300]
                    used.add(key)
            enriched.append(item)
        return enriched

    async def enrich_answer_pois(
        self,
        answer: str,
        result: dict[str, Any],
        evidence: list[EvidenceItem] | None = None,
    ) -> dict[str, Any]:
        """Attach verified photos for attractions newly mentioned by an answer.

        A named image from a fetched web page is a useful fallback when the
        map provider cannot resolve a secondary attraction.  It is still
        subject to :meth:`attach_evidence_images` name matching and therefore
        cannot silently turn a Beijing image into a Luoyang POI.
        """

        destination = str(result.get("destination") or "").strip()
        if not destination:
            return result
        existing = [
            dict(item) for item in (result.get("pois") or []) if isinstance(item, dict)
        ]
        try:
            existing = await self.amap_tool.enrich_poi_locations(
                existing, destination
            )
        except (RuntimeError, ValueError, OSError):
            # Keep answer/media enrichment available when geocoding has a
            # transient failure. The map builder will omit only unresolved
            # items instead of failing the whole response.
            pass
        raw_map = result.get("map")
        raw_points = raw_map.get("points", []) if isinstance(raw_map, dict) else []
        map_points = raw_points if isinstance(raw_points, list) else []

        def finish(items: list[dict[str, Any]]) -> dict[str, Any]:
            # Resolution can add a POI after synthesis. Run the same two
            # description bridges once more so a detailed model paragraph is
            # not lost merely because the map provider resolved that POI
            # lazily. Existing grounded descriptions are preserved.
            combined = self.attach_answer_descriptions(items[:20], answer)
            if evidence:
                combined = self.attach_poi_descriptions(combined, evidence)
            updated = {**result, "pois": combined}
            if isinstance(raw_map, dict):
                updated["map"] = {
                    **raw_map,
                    "points": self.map_tool.build_points(
                        combined, result.get("days_plan") or []
                    ),
                }
            return updated

        # Older payloads sometimes kept media only on compact map points.
        for item in existing:
            if item.get("photo") or item.get("photos"):
                continue
            name = str(item.get("name") or "")
            for point in map_points:
                if not isinstance(point, dict):
                    continue
                point_name = str(point.get("name") or "")
                if name and point_name and (name in point_name or point_name in name):
                    if point.get("photo") or point.get("photos"):
                        item.update(
                            {
                                key: value
                                for key, value in point.items()
                                if key in {"photo", "photos"} and value
                            }
                        )
                    break

        candidates = self.extract_answer_landmarks(answer)
        if not candidates:
            return finish(existing)

        def existing_index(candidate: str) -> int | None:
            return next(
                (
                    index
                    for index, item in enumerate(existing)
                    if candidate in str(item.get("name") or "")
                    or str(item.get("name") or "") in candidate
                    or candidate in self.poi_display_name(item)
                    or self.poi_display_name(item) in candidate
                ),
                None,
            )

        def has_media(item: dict[str, Any]) -> bool:
            return bool(item.get("photo") or item.get("photos"))

        def has_location(item: dict[str, Any]) -> bool:
            return self.map_tool.has_valid_location(item.get("location"))

        names_to_resolve = [
            candidate
            for candidate in candidates
            if existing_index(candidate) is None
            or not has_media(existing[existing_index(candidate)])
            or not has_location(existing[existing_index(candidate)])
        ]
        if not names_to_resolve:
            return finish(existing)

        async def resolve(name: str) -> dict[str, Any]:
            match_index = existing_index(name)
            try:
                item = await self.amap_tool.resolve_poi(name, destination)
            except (RuntimeError, ValueError):
                item = {}
            if not isinstance(item, dict):
                item = {}
            if item:
                canonical = str(item.get("name") or "")
                searchable = " ".join(
                    str(item.get(field) or "")
                    for field in ("name", "address", "type", "alias")
                )
                if name not in searchable and canonical not in name:
                    item = {}
            # A free-form geocoder can return coordinates for prose such as
            # “紧邻太湖” or “古镇历史”. It is not evidence that the text names a
            # real POI. Never add a newly mentioned entity when the provider
            # explicitly reports a geocode-only resolution.
            if match_index is None and str(item.get("resolution_method") or "") == "geocode":
                item = {}
            # Coordinate enrichment is safe only after POI text search has
            # verified the entity, or for a POI already present in the
            # structured result. It must not promote an arbitrary heading.
            if item and not has_location(item):
                seed = item
                try:
                    located = await self.amap_tool.enrich_poi_locations(
                        [seed], destination
                    )
                except (RuntimeError, ValueError, OSError):
                    located = []
                if located and has_location(located[0]):
                    item = {**item, **located[0]}
            if not item:
                return {}
            if self.is_supporting_poi(item):
                return {}
            media = self.normalise_poi_media([item])
            item = media[0] if media else item
            if evidence and not has_media(item):
                web_match = self.attach_evidence_images(
                    [item], evidence, destination=destination
                )
                if web_match:
                    item = web_match[0]
            return item if has_location(item) or has_media(item) else {}

        resolved = await asyncio.gather(*(resolve(name) for name in names_to_resolve))
        additions: list[dict[str, Any]] = []
        seen = {str(item.get("name") or "").strip() for item in existing}
        for candidate, item in zip(names_to_resolve, resolved):
            if not item and evidence:
                web_match = self.attach_evidence_images(
                    [{"name": candidate}], evidence, destination=destination
                )
                if web_match and web_match[0].get("photo"):
                    item = web_match[0]
            if not item:
                continue
            match_index = existing_index(candidate)
            if match_index is not None:
                non_empty = {
                    key: value
                    for key, value in item.items()
                    if value not in (None, "", [])
                }
                existing[match_index] = {**existing[match_index], **non_empty}
            else:
                name = str(item.get("name") or "").strip()
                if name and name not in seen:
                    additions.append(item)
                    seen.add(name)
        combined = [*existing, *additions][:20]
        return finish(combined)
