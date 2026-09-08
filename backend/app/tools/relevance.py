"""Small, deterministic relevance guards for travel search results.

The language model still decides how to explain the results.  These helpers only
remove an obviously wrong category (for example, a hotel page from an attraction
query) before evidence is shown to the model or linked in the UI.
"""

import re
from typing import Any, Literal, cast
from urllib.parse import unquote

from backend.app.agent.intent import rule_classify

SearchIntent = Literal["attraction", "hotel", "restaurant", "shopping", "general"]

COMMON_DESTINATIONS = (
    "北京",
    "上海",
    "广州",
    "深圳",
    "杭州",
    "苏州",
    "郑州",
    "成都",
    "西安",
    "重庆",
    "南京",
    "武汉",
    "长沙",
    "厦门",
    "福州",
    "青岛",
    "大连",
    "天津",
    "济南",
    "合肥",
    "昆明",
    "桂林",
    "三亚",
    "海口",
    "哈尔滨",
    "沈阳",
    "洛阳",
    "开封",
    "无锡",
    "宁波",
    "乌鲁木齐",
    "拉萨",
    "香港",
    "澳门",
    "台北",
)

INTENT_TERMS: dict[SearchIntent, tuple[str, ...]] = {
    "attraction": (
        "景点",
        "景区",
        "风景名胜",
        "博物馆",
        "公园",
        "古镇",
        "名胜",
        "游玩",
        "观光",
        "遗址",
        "古迹",
        "自然风光",
        "主题乐园",
        "动物园",
        "植物园",
        "纪念馆",
        "展馆",
        "故居",
        "景观",
        # A few common URL/title words returned by overseas search providers.
        "attraction",
        "attractions",
        "scenic",
        "sights",
        "museum",
        "museums",
        "park",
        "parks",
        "landmark",
    ),
    "hotel": (
        "酒店",
        "住宿",
        "民宿",
        "客栈",
        "旅馆",
        "宾馆",
        "酒店公寓",
        "青年旅舍",
        "旅社",
        "住哪",
        "住在",
        "hotel",
        "hotels",
        "hostel",
        "hostels",
        "accommodation",
        "lodging",
    ),
    "restaurant": (
        "餐厅",
        "餐馆",
        "饭店",
        "美食",
        "小吃",
        "餐饮",
        "火锅",
        "烧烤",
        "咖啡",
        "甜品",
        "用餐",
        "餐吧",
        "restaurant",
        "restaurants",
        "food",
        "dining",
    ),
    "shopping": (
        "购物",
        "商场",
        "商城",
        "商业街",
        "步行街",
        "奥特莱斯",
        "免税店",
        "市场",
        "shopping",
        "mall",
        "malls",
        "market",
        "markets",
    ),
    # General travel, route and cost questions should not be filtered as if
    # they were attraction searches.  Their relevance is determined by the
    # embedding ranker and the final model using the original question.
    "general": (),
}

# These categories commonly appear in a broad web/POI search but are not a
# destination/attraction result.  They are treated as exclusions only when the
# requested category is absent, so a comprehensive guide mentioning hotels or
# food alongside sights is still usable.
_NON_ATTRACTION_TERMS = (
    *INTENT_TERMS["hotel"],
    *INTENT_TERMS["restaurant"],
    *INTENT_TERMS["shopping"],
    "交通",
    "公交",
    "地铁",
    "火车站",
    "机场",
    "汽车站",
    "汽车服务",
    "汽车销售",
    "汽车维修",
    "汽车园区",
    "4s店",
    "商务住宅",
    "住宅区",
    "住宅小区",
    "写字楼",
    "公司企业",
    "产业园",
    "工业园",
    "物流园",
    "银行",
    "hospital",
    "医院",
)

_MIXED_GUIDE_TERMS = ("攻略", "指南", "游玩", "行程", "路线")
_LANDMARK_SUFFIX = (
    "湖", "寺", "山", "塔", "岛", "湾", "滩", "石窟", "古镇", "景区",
    "博物馆", "公园", "故居", "遗址", "园", "广场", "街", "巷", "堤", "门", "城", "阁",
    "楼", "祠", "宫", "殿", "馆", "陵", "庙", "瀑布", "古城", "城墙",
)
_POI_FACILITY_TERMS = (
    "售票处", "补票处", "服务区", "游客中心", "公交站", "停车场", "票务中心",
    "检票口", "讲解服务", "购物中心", "宾馆", "酒店", "餐厅",
)

# 高德一级 POI 类型中明确不属于旅游景点的类别。风景名胜为 11xxxx，
# 科教文化场馆常为 14xxxx；08xxxx 中还可能包含可游玩的休闲场所，因此不在
# 这里一刀切。只有在响应携带明确类型码时才应用该排除表，避免靠名称猜测。
_NON_ATTRACTION_TYPE_PREFIXES = frozenset(
    {
        "01", "02", "03", "04", "05", "06", "07", "09", "10", "12",
        "13", "15", "16", "17", "18", "19", "20", "21", "22", "97", "99",
    }
)
_UNAVAILABLE_POI_TERMS = (
    "暂停开放",
    "暂停营业",
    "临时闭馆",
    "停止开放",
    "永久关闭",
    "已关闭",
)

_DESCRIPTIVE_NAME_PREFIX = re.compile(
    r"^(?:从(?!化|江)|由|到|前往|位于|坐落于?|紧邻|毗邻|邻近|靠近|周边|附近|这里|"
    r"景点类型|方便|推荐|适合|可以|[\u4e00-\u9fff]{2,6}的景点)"
)
_DESCRIPTIVE_NAME_ENDING = re.compile(
    r"(?:历史|文化|山色|山水|风光|特色|选择|推荐|体验|景点类型)$"
)


def is_probably_descriptive_poi_name(name: str) -> bool:
    """Return false for prose fragments masquerading as POI names."""

    value = " ".join(str(name or "").split()).strip()
    if not value:
        return False
    return not (
        _DESCRIPTIVE_NAME_PREFIX.search(value)
        or _DESCRIPTIVE_NAME_ENDING.search(value)
    )

# Amap text/around search frequently returns a product, activity or route as
# if it were a place.  Those records are useful for an activity question, but
# they must not become an attraction card in an itinerary (for example
# ``西湖经典环线`` or ``河坊街夜游``).  Keep this list about the *entity kind*,
# rather than any city/landmark name, so the guard works for every destination.
_NON_SCENIC_ENTITY_TERMS = (
    "环线",
    "环湖线",
    "游览线",
    "游线",
    "线路",
    "路线",
    "步行线路",
    "观光线路",
    "夜游",
    "灯光秀",
    "灯光演出",
    "演出",
    "演艺",
    "活动",
    "套餐",
    "项目",
    "观光车",
    "接驳车",
    "游船",
    "打卡点",
    "打卡线路",
    "体验项目",
    "一日游",
    "两日游",
    "半日游",
    "跟团游",
    "自由行",
    "旅拍",
)


def _text(value: Any) -> str:
    if value is None:
        return ""
    return unquote(str(value)).strip().lower()


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def extract_landmark_terms(text: str) -> list[str]:
    """Extract explicit landmark names for map-query expansion.

    This is intentionally a small NER fallback rather than a city/landmark
    whitelist. It recognizes names used after common travel verbs and direct
    short queries such as ``龙门石窟``; the map provider remains responsible
    for canonical POI resolution.
    """
    normalized = " ".join(str(text or "").split())
    if not normalized:
        return []
    suffixes = "|".join(_LANDMARK_SUFFIX)
    terms: list[str] = []

    def clean_candidate(raw: str) -> str:
        value = str(raw or "").strip(" ，,。；;、的和与及")
        # A regex match may start at the city or a verb (for example
        # “宁波看天一阁”). Keep the final landmark phrase, not the sentence.
        value = re.split(
            r"(?:我想(?:去|问)?|我问|请问|帮我(?:找|查|介绍)|推荐|看看|看|了解|介绍|查询|搜索|有|是|去|到|前往|游览|参观)",
            value,
        )[-1]
        match = re.search(rf"([\u4e00-\u9fff]{{2,12}}(?:{suffixes}))$", value)
        return (match.group(1) if match else value).strip(" ，,。；;、的和与及")

    for pattern in (
        rf"(?:游览|参观|去|包括|重点|安排|打卡|推荐|看看|到)\s*([\u4e00-\u9fff]{{2,12}}?(?:{suffixes}))",
        rf"(?:和|与|及|、)\s*([\u4e00-\u9fff]{{2,12}}(?:{suffixes}))",
    ):
        for match in re.finditer(pattern, normalized):
            value = clean_candidate(match.group(1))
            if value and value not in terms:
                terms.append(value)
    if not terms and len(normalized) <= 40:
        direct = re.search(rf"([\u4e00-\u9fff]{{2,12}}(?:{suffixes}))", normalized)
        if direct:
            value = clean_candidate(direct.group(1))
            if value:
                terms.append(value)
    for landmark in ("西湖", "灵隐寺", "故宫", "长城", "兵马俑"):
        if landmark in normalized and landmark not in terms:
            terms.append(landmark)
    return terms[:6]


def classify_search_intent(text: str) -> SearchIntent:
    """Return the search category from the shared rules fallback.

    Agents use :class:`TravelIntentClassifier` for the model-first decision.
    This synchronous adapter remains for the web tool and backwards-compatible
    callers that do not have an LLM instance available.
    """

    return cast(SearchIntent, rule_classify(text).search_intent)


def infer_search_destination(text: str) -> str:
    """Return the latest known city in a search query, if one is present."""

    normalized = _text(text)
    matches = [
        (normalized.rfind(city), city)
        for city in COMMON_DESTINATIONS
        if normalized.rfind(city) >= 0
    ]
    return max(matches)[1] if matches else ""


def is_destination_compatible(text: str, destination: str) -> bool:
    """Reject a page that explicitly belongs to a different common city.

    A page with no city in its title/URL/snippet is retained because many
    attractions are branded by their landmark rather than their city.  This is
    a guard against explicit cross-city mismatches, not a hard geocoder.
    """

    target = _text(destination).removesuffix("市")
    if not target or target not in COMMON_DESTINATIONS:
        return True
    normalized = _text(text)
    places = [city for city in COMMON_DESTINATIONS if city in normalized]
    return not any(city != target for city in places)


def build_search_query(destination: str, message: str, intent: SearchIntent) -> str:
    """Add category anchors while retaining the user's place and preferences."""

    destination = destination.strip()
    message = message.strip()
    base = message if destination and destination in message else " ".join(
        part for part in (destination, message) if part
    )
    expansions = {
        "attraction": "景点 景区 博物馆 公园 古镇 旅游攻略",
        "hotel": "酒店 住宿 民宿 周边位置",
        "restaurant": "餐厅 美食 小吃 餐饮 推荐",
        "shopping": "购物 商场 商业街 购物攻略",
        "general": "旅游 旅行 信息 参考",
    }
    return " ".join(part for part in (base, expansions[intent]) if part).strip()


def is_relevant_category(
    text: str, intent: SearchIntent, *, allow_mixed: bool = True
) -> bool:
    """Return false only for an explicit, obviously mismatched category.

    Generic travel guides are kept.  We intentionally do not inspect the whole
    article body here: an attraction guide is allowed to mention where to eat or
    stay.  Title, URL and search snippets are the safer category signals.
    """

    if intent == "general":
        return True
    normalized = _text(text)
    if not normalized:
        return True
    positive = _contains_any(normalized, INTENT_TERMS[intent])
    other_terms = tuple(
        term
        for other_intent, terms in INTENT_TERMS.items()
        if other_intent != intent
        for term in terms
    )
    has_other = _contains_any(normalized, other_terms)
    if positive and has_other:
        # A URL/category path is a stronger signal than a mixed article title;
        # callers can set allow_mixed=False for that case.
        if not allow_mixed:
            return classify_search_intent(normalized) == intent
        # Keep comprehensive guides, but reject titles such as “景区附近酒店
        # 推荐” where the non-requested category is clearly the product.
        if intent == "attraction":
            return _contains_any(normalized, _MIXED_GUIDE_TERMS)
        return True
    if positive:
        return True
    if has_other:
        return intent == "attraction" and _contains_any(normalized, _MIXED_GUIDE_TERMS)
    if intent == "attraction":
        return not _contains_any(normalized, _NON_ATTRACTION_TERMS)
    return True


def filter_evidence_items(
    items: list[Any], intent: SearchIntent, destination: str = ""
) -> list[Any]:
    """Filter evidence by title/URL/snippet without deleting useful article text."""

    filtered: list[Any] = []
    for item in items:
        metadata = getattr(item, "metadata", {}) or {}
        title = _text(getattr(item, "title", ""))
        url = _text(getattr(item, "url", ""))
        snippet = _text(metadata.get("snippet", ""))
        source_text = _text(
            " ".join(
                (
                    title,
                    snippet,
                    _text(metadata.get("source_title", "")),
                    _text(metadata.get("source_domain", "")),
                )
            )
        )
        if is_destination_compatible(
            f"{source_text} {url}", destination
        ) and is_relevant_category(source_text, intent) and (
            not url or is_relevant_category(url, intent, allow_mixed=False)
        ):
            filtered.append(item)
    return filtered


def filter_poi_items(
    items: list[dict[str, Any]],
    intent: SearchIntent,
    destination: str = "",
    *,
    for_itinerary: bool = False,
) -> list[dict[str, Any]]:
    """Remove POIs whose explicit name/type identifies another category.

    ``for_itinerary`` additionally removes route and activity products that
    should not consume a day-plan or attraction-card slot.  They remain
    eligible in a direct activity search, where something such as a named
    night cruise can be exactly what the user requested.
    """

    filtered: list[dict[str, Any]] = []
    for item in items:
        name = _text(item.get("name", ""))
        poi_type = _text(item.get("type", ""))
        other_fields = " ".join(
            _text(item.get(field, "")) for field in ("typecode", "address")
        )
        city = _text(item.get("city", ""))
        if not is_destination_compatible(
            f"{name} {poi_type} {other_fields} {city}", destination
        ):
            continue
        # Amap's type field is the strongest category signal.  Names and
        # addresses may contain a landmark plus nearby businesses, so mixed
        # names remain eligible unless the type explicitly disagrees.
        if poi_type and not is_relevant_category(
            poi_type, intent, allow_mixed=False
        ):
            continue
        if intent == "attraction":
            if _contains_any(name, _UNAVAILABLE_POI_TERMS):
                continue
            if not is_probably_descriptive_poi_name(name):
                continue
            # Do this after the category/type checks: a legitimate scenic POI
            # can mention a nearby activity in its address, while a record
            # whose own name is a route/product is not a point of interest.
            # ``is_supporting_poi`` handles ordinary facilities (ticket
            # office, parking lot, etc.); this guard covers the less obvious
            # route/activity records returned by broad city searches.
            if for_itinerary and _contains_any(name, _NON_SCENIC_ENTITY_TERMS):
                continue
            typecodes = re.findall(r"(?<!\d)(\d{6})(?!\d)", other_fields)
            has_scenic_type = any(code.startswith("110") for code in typecodes)
            has_explicit_non_scenic_type = any(
                code[:2] in _NON_ATTRACTION_TYPE_PREFIXES for code in typecodes
            )
            if has_explicit_non_scenic_type and not has_scenic_type:
                continue
            # City-wide POI searches may put office buildings, residential
            # compounds and other non-scenic records before actual sights.
            # Keep a result only when its Amap scenic type code or name/type
            # carries an attraction signal. This is intentionally generic so
            # it works for any city and does not depend on a city whitelist.
            # Do not use the address as a scenic signal. Business addresses
            # such as “汽车园区” contain “园”, which previously caused car
            # dealerships to be treated as attractions.
            scenic_text = f"{name} {poi_type}"
            scenic_signal = (
                str(item.get("typecode") or "").startswith("110")
                or _contains_any(scenic_text, INTENT_TERMS["attraction"])
                or _contains_any(scenic_text, _LANDMARK_SUFFIX)
            )
            if not scenic_signal:
                continue
        if is_relevant_category(f"{name} {other_fields}", intent):
            filtered.append(item)
    return filtered


def deduplicate_poi_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse exact and parent/child POI duplicates while keeping main sites.

    Amap can return a landmark together with internal points such as
    ``故宫博物院-午门``. They are useful map details but should not occupy two
    separate itinerary slots. The unsuffixed parent wins when it is present;
    otherwise the shortest/highest-rated observed result is retained.
    """

    selected: dict[str, tuple[int, dict[str, Any]]] = {}

    def family(name: str) -> tuple[str, bool]:
        parent = re.split(r"\s*[-—–]\s*|[（(]", name, maxsplit=1)[0].strip()
        normalized = re.sub(r"\s+", "", parent).casefold()
        return normalized, parent == name.strip()

    def quality(item: dict[str, Any], is_parent: bool) -> tuple[int, float, int]:
        try:
            rating = float(str(item.get("rating") or 0))
        except (TypeError, ValueError):
            rating = 0.0
        name = str(item.get("name") or "")
        return int(is_parent), rating, -len(name)

    for position, item in enumerate(items):
        name = _text(item.get("name", ""))
        if not name:
            continue
        key, is_parent = family(name)
        current = selected.get(key)
        if current is None:
            selected[key] = (position, item)
            continue
        current_item = current[1]
        _, current_is_parent = family(_text(current_item.get("name", "")))
        if quality(item, is_parent) > quality(current_item, current_is_parent):
            selected[key] = (current[0], item)

    return [item for _, item in sorted(selected.values(), key=lambda value: value[0])]


def filter_pois_by_landmarks(
    items: list[dict[str, Any]], landmark_terms: list[str]
) -> list[dict[str, Any]]:
    """Keep only POIs matching explicit landmarks from the user request."""
    terms = [_text(term) for term in landmark_terms if _text(term)]
    if not terms or not items:
        return items
    matched = []
    for item in items:
        searchable = _text(" ".join(str(item.get(field) or "") for field in ("name", "address", "type", "alias")))
        if any(term in searchable or searchable in term for term in terms):
            matched.append(item)
    if not matched:
        return []
    scenic = [
        item for item in matched
        if not any(term in _text(item.get("name")) for term in _POI_FACILITY_TERMS)
    ]
    return scenic or matched
