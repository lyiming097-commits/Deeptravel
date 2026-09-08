"""路线 Agent 的纯函数：地点、日期和交通偏好解析。"""

import re
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

KNOWN_CITIES = (
    "成都", "北京", "上海", "杭州", "西安", "重庆", "广州", "深圳", "南京", "苏州",
    "郑州", "洛阳", "开封", "合肥", "济南", "青岛", "武汉", "长沙", "南昌", "福州",
    "厦门", "宁波", "无锡", "常州", "天津", "石家庄", "太原", "沈阳", "大连", "长春",
    "哈尔滨", "海口", "三亚", "昆明", "贵阳", "桂林", "兰州", "乌鲁木齐", "西宁",
    "银川", "呼和浩特",
)
TRANSIT_KEYWORDS = (
    "公交", "地铁", "公共交通", "高铁", "动车", "火车", "铁路", "列车", "城际", "G字头",
)


def list_value(value: Any, key: str) -> list[dict[str, Any]]:
    items = value.get(key) if isinstance(value, dict) else None
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def first_train_code(trains: list[dict[str, Any]]) -> str:
    for train in trains:
        code = str(train.get("train_no") or train.get("train_code") or "").strip()
        if code:
            return code
    return ""


def _departure_clock(train: dict[str, Any]) -> tuple[int, int] | None:
    for key in ("departure_time", "depart_time", "start_time", "departure", "from_time", "出发时间"):
        value = str(train.get(key) or "").strip()
        match = re.search(r"(?<!\d)(\d{1,2})[:：](\d{2})", value)
        if match:
            hour, minute = int(match.group(1)), int(match.group(2))
            if 0 <= hour < 24 and 0 <= minute < 60:
                return hour, minute
    return None


def _time_bucket(train: dict[str, Any]) -> str:
    clock = _departure_clock(train)
    if clock is None:
        return "unknown"
    hour = clock[0]
    return "morning" if hour < 12 else "afternoon" if hour < 18 else "evening"


def select_train_samples(
    trains: list[dict[str, Any]], limit: int, query_text: str = ""
) -> list[dict[str, Any]]:
    """Select a small, time-diverse sample for a railway answer.

    With no period preference, distribute results across morning, afternoon
    and evening.  An explicit period keeps that period first and fills any
    remaining slots from the provider's normal ranking.
    """
    if not trains:
        return []
    limit = max(1, min(limit, 50))
    text = query_text.lower()
    requested = None
    if any(term in text for term in ("早上", "上午", "清晨", "早间")):
        requested = "morning"
    elif any(term in text for term in ("中午", "下午", "傍晚", "午后")):
        requested = "afternoon"
    elif any(term in text for term in ("晚上", "夜间", "深夜", "晚间")):
        requested = "evening"
    if requested is None:
        clock_hint = re.search(r"(?<!\d)(\d{1,2})\s*点", text)
        if clock_hint:
            hour = int(clock_hint.group(1))
            if 0 <= hour < 12:
                requested = "morning"
            elif hour < 18:
                requested = "afternoon"
            else:
                requested = "evening"
    if requested:
        # An explicit period is a hard filter: do not fill the result with
        # trains from other periods just because the preferred period has
        # fewer results (or because the provider returned fewer than `limit`).
        preferred = [train for train in trains if _time_bucket(train) == requested]
        return preferred[:limit]
    buckets = {
        name: [train for train in trains if _time_bucket(train) == name]
        for name in ("morning", "afternoon", "evening")
    }
    selected: list[dict[str, Any]] = []
    for index in range(limit):
        bucket = ("morning", "afternoon", "evening")[index % 3]
        if buckets[bucket]:
            selected.append(buckets[bucket].pop(0))
    remaining = [train for train in trains if train not in selected]
    return (selected + remaining)[:limit]


def mode_action(value: str) -> str:
    lowered = value.lower()
    if any(word in lowered for word in ("步行", "walk")):
        return "route_walking"
    if any(word in lowered for word in TRANSIT_KEYWORDS):
        return "route_transit"
    if any(word in lowered for word in ("开车", "驾车", "drive", "driving")):
        return "route_driving"
    return "route_transit"


def safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def format_date(year: str, month: str, day: str) -> str:
    candidate = safe_date(int(year), int(month), int(day))
    return candidate.isoformat() if candidate else ""


def normalise_date(value: str) -> str:
    if not value:
        return ""
    match = re.fullmatch(
        r"(20\d{2})\s*[-/.年]\s*(\d{1,2})\s*[-/.月]\s*(\d{1,2})\s*日?", value
    )
    return format_date(*match.groups()) if match else ""


def today() -> date:
    return datetime.now(ZoneInfo("Asia/Shanghai")).date()


def extract_train_date(context: str, parameters: dict[str, Any]) -> str:
    for key in ("train_date", "departure_date", "date"):
        parsed = normalise_date(str(parameters.get(key) or "").strip())
        if parsed:
            return parsed
    iso = re.search(
        r"(20\d{2})\s*[-/.年]\s*(\d{1,2})\s*[-/.月]\s*(\d{1,2})\s*日?", context
    )
    if iso:
        return format_date(*iso.groups())
    chinese = re.search(r"(?:(20\d{2})\s*年)?\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", context)
    if chinese:
        current = today()
        year = int(chinese.group(1) or current.year)
        month, day = int(chinese.group(2)), int(chinese.group(3))
        candidate = safe_date(year, month, day)
        if not chinese.group(1) and candidate and candidate < current:
            year += 1
        return format_date(str(year), str(month), str(day))
    # Numeric relative dates are common in natural language ("2天后" is
    # two days after today, not necessarily the colloquial "明天").  Prefer
    # this explicit offset over any contradictory parenthetical wording.
    relative = re.search(r"(?P<offset>\d{1,2})\s*天后", context)
    if relative:
        return (today() + timedelta(days=int(relative.group("offset")))).isoformat()
    # Also accept common Chinese numerals used for relative offsets.
    chinese_offsets = {"一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7}
    relative_cn = re.search(r"(?P<offset>[一两二三四五六七])\s*天后", context)
    if relative_cn:
        return (today() + timedelta(days=chinese_offsets[relative_cn.group("offset")])).isoformat()
    for word, offset in {"今天": 0, "明天": 1, "后天": 2, "大后天": 3}.items():
        if word in context:
            return (today() + timedelta(days=offset)).isoformat()
    return ""


def endpoint_city(value: str) -> str:
    text = value.strip()
    matches = [city for city in KNOWN_CITIES if city in text]
    if matches:
        return max(matches, key=len)
    match = re.search(r"([\u4e00-\u9fff]{2,8})市(?:东|西|南|北)?(?:站)?$", text)
    return match.group(1) if match else ""


def clean_railway_station_query(value: str) -> str:
    """Remove conversational station descriptors before a 12306 lookup.

    Users and the LLM often say ``郑州高铁站`` or ``南京火车站`` while the
    12306 station dictionary uses ``郑州``/``南京`` (or ``郑州东``/``南京南``).
    The MCP accepts those canonical names, but rejects the conversational
    suffixes.  Keep actual directional station names intact by removing only
    the transport descriptor plus the trailing ``站``.
    """

    station = value.strip(" ，,。；;、")
    station = re.sub(r"(?:高铁|动车|火车|铁路|列车|客运)?站$", "", station)
    station = re.sub(r"(?:高铁|动车|火车|铁路|列车)$", "", station)
    return station.removesuffix("市").strip(" ，,。；;、")


def contains_city(value: str, city: str) -> bool:
    return city.rstrip("市") in value


def is_cross_city(origin: str, destination: str, city: str, context: str) -> bool:
    if any(word in context for word in ("跨城", "跨市", "异地", "城际")):
        return True
    if city and contains_city(origin, city) and contains_city(destination, city):
        return False
    left, right = endpoint_city(origin), endpoint_city(destination)
    return bool(left and right and left != right)


def looks_like_local_landmark(value: str) -> bool:
    text = value.strip()
    if not text:
        return True
    markers = (
        "景区", "景点", "湿地", "古镇", "外滩", "公园", "博物馆", "体育馆", "大学", "机场",
        "码头", "酒店", "商场", "广场", "火车站", "高铁站", "地铁站", "客运站", "汽车站",
    )
    return any(marker in text for marker in markers) or text.endswith(("湖", "寺", "塔", "园", "湾"))


def clean_endpoint(value: str, field: str) -> str:
    endpoint = value.strip(" ，,。；;、")
    if field == "origin":
        positions = [endpoint.rfind(city) for city in KNOWN_CITIES]
        last_city = max(positions, default=-1)
        if last_city > 0:
            endpoint = endpoint[last_city:]
        # A greedy natural-language route pattern may capture the transport
        # phrase as part of the origin (e.g. "郑州坐火车去大连").  Remove only
        # that suffix; station names such as "郑州东站" remain intact.
        endpoint = re.split(
            r"(?:坐|乘坐|乘|搭乘|选择|使用)\s*(?:火车|高铁|动车|列车|铁路|飞机|航班|汽车|大巴|公交|地铁)",
            endpoint,
            maxsplit=1,
        )[0]
        return re.sub(r"^(?:帮我|请帮我|请|想要|想|查询|规划|安排|路线|一下)+", "", endpoint)
    endpoint = re.split(
        r"(?:大后天|后天|明天|今天|\d{1,2}\s*天后|"
        r"20\d{2}\s*年?\s*\d{1,2}\s*月\s*\d{1,2}\s*日?|"
        r"\d{1,2}\s*月\s*\d{1,2}\s*日|"
        r"想坐|想用|请用|乘坐|坐|乘|路线|怎么走|如何走|需要多久|要多久|玩|旅游|旅行|游玩|"
        r"公交|地铁|高铁|动车|火车|铁路|城际|驾车|开车|步行|车次|班次|余票|票价|经停站|时刻表|"
        r"查询|信息|吧|呢)",
        endpoint,
        maxsplit=1,
    )[0]
    return endpoint.strip(" ，,。；;、的")


def extract_parameters(message: str) -> dict[str, str]:
    text = "\n".join(" ".join(line.split()) for line in message.splitlines() if line.strip())
    patterns = (
        r"从\s*(?P<origin>[^，,。；;\s]+?)\s*出发.*?(?:到|至|前往|去)\s*(?P<destination>[^，,。；;\s]+)",
        r"从\s*(?P<origin>[^，,。；;\s]+?)\s*(?:到|至|前往|去)\s*(?P<destination>[^，,。；;\s]+)",
        r"由\s*(?P<origin>[^，,。；;\s]+?)\s*(?:到|至|前往)\s*(?P<destination>[^，,。；;\s]+)",
    )
    candidates: list[tuple[int, int, re.Match[str]]] = []
    for priority, pattern in enumerate(patterns):
        candidates.extend((m.start(), priority, m) for m in re.finditer(pattern, text))
    city_pattern = "|".join(map(re.escape, KNOWN_CITIES))
    pair = rf"(?P<origin>{city_pattern})\s*(?:到|至|前往|去)\s*(?P<destination>{city_pattern})"
    candidates.extend((m.start(), 2, m) for m in re.finditer(pair, text))
    generic = r"(?P<origin>[\u4e00-\u9fff]{2,20}?)\s*(?:到|至|前往|去)\s*(?P<destination>[\u4e00-\u9fff]{2,20})"
    candidates.extend((m.start(), 3, m) for m in re.finditer(generic, text))

    # A relative-date phrase can itself look like the origin of a generic
    # ``X 到 Y`` match (e.g. ``从郑州出发，明天到北京``).  Discard such
    # false candidates so the more specific ``从…出发…到…`` pattern wins.
    temporal_origin = re.compile(r"^(?:今天|明天|后天|大后天|\d{1,2}\s*天后)$")
    candidates = [
        item
        for item in candidates
        if not temporal_origin.fullmatch(
            clean_endpoint(str(item[2].groupdict().get("origin") or ""), "origin")
        )
    ]

    endpoints: dict[str, str] = {}
    start = -1
    if candidates:
        start, priority, match = max(
            candidates, key=lambda item: (item[0], item[2].end() - item[2].start(), -item[1])
        )
        # Normalize every pattern, not only the generic fallback.  Otherwise
        # the high-priority "从…到…" pattern can leave transport words in the
        # station name ("郑州坐火车"), which 12306 cannot resolve.
        endpoints = {
            key: clean_endpoint(value, key) for key, value in match.groupdict().items()
        }
        endpoints = {key: value for key, value in endpoints.items() if value}

    city_matches = list(re.finditer(rf"(?:位于|城市是|(?<![现正])在)\s*(?P<city>{city_pattern})", text))
    city_match = city_matches[-1] if city_matches else None
    endpoint_text = " ".join(endpoints.get(key, "") for key in ("origin", "destination"))
    endpoint_cities = {city for city in KNOWN_CITIES if city in endpoint_text}
    turn_start = text.rfind("\n", 0, max(start, 0)) + 1
    if len(endpoint_cities) > 1:
        endpoints.pop("city", None)
    elif city_match and city_match.start() >= turn_start:
        endpoints["city"] = city_match.group("city")
    elif len(endpoint_cities) == 1:
        endpoints["city"] = next(iter(endpoint_cities))
    elif city_match:
        endpoints["city"] = city_match.group("city")

    mode_text = text[turn_start:] if start >= 0 else text.rsplit("\n", 1)[-1]
    mode = mode_action(mode_text)
    if mode != "route_transit" or any(word in mode_text for word in TRANSIT_KEYWORDS):
        endpoints["mode"] = mode.removeprefix("route_")
    if any(word in mode_text for word in ("高铁", "G字头")):
        endpoints["transport_preference"] = "high_speed_rail"
    elif "动车" in mode_text:
        endpoints["transport_preference"] = "bullet_train"
    elif any(word in mode_text for word in ("火车", "铁路", "列车", "城际")):
        endpoints["transport_preference"] = "rail"
    elif any(word in mode_text for word in ("飞机", "航班", "机票", "航空")):
        endpoints["transport_preference"] = "air"
    return endpoints


def railway_fallback(result: dict[str, Any]) -> str:
    trains = result.get("trains") or []
    if not trains:
        lines = [
            "铁路车次查询结果",
            f"{result['origin']} → {result['destination']}",
            f"出发日期：{result['train_date']}",
            "暂未查到直达车次。",
        ]
    else:
        display_trains = trains[:9]
        lines = [
            "铁路车次查询结果",
            f"{result['origin']} → {result['destination']}",
            f"出发日期：{result['train_date']}",
        ]
        # ``run_railway`` already applies the configured display limit (nine
        # by default).  Keep the fallback in sync so a provider/LLM failure
        # does not silently hide the ninth selected train.
        for train in display_trains:
            code = train.get("train_no") or train.get("train_code") or "未知车次"
            timing = f"{train.get('start_time', '--')}—{train.get('arrive_time', '--')}"
            seats = train.get("seats") or {}
            available = "、".join(f"{name}:{value}" for name, value in seats.items() if value)
            suffix = f"，余票 {available}" if available else ""
            lines.append(
                f"- {code}｜{timing}｜历时 {train.get('duration') or '未知'}{suffix}"
            )
        total = result.get("total_trains", len(trains))
        # Keep the total/display wording stable for API clients while placing
        # it on its own line for the chat layout.
        lines.insert(3, f"查到 {total} 趟直达车次，先列出 {len(display_trains)} 趟：")
    if result.get("transfers"):
        lines.extend(["中转换乘", f"另有 {len(result['transfers'])} 个中转换乘方案可参考。"])
    if result.get("stops"):
        lines.extend(["经停信息", f"已获取其中一趟列车的 {len(result['stops'])} 个经停站。"])
    lines.extend(["出行提示", "余票、票价和开行情况以 12306 实时查询结果为准。"])
    return "\n".join(lines)


def route_answer_fallback(
    route: dict[str, Any],
    distance: dict[str, Any],
    origin: str,
    destination: str,
    preference: str = "",
) -> str:
    """Build a readable route answer when the answer model is unavailable.

    Keep this fallback deliberately data-driven: every value shown below comes
    from the map observation, while headings and line breaks make the same
    response easy to scan in both the browser and mini-program chat bubbles.
    """

    mode = str(route.get("mode") or "交通").strip()
    trips = [
        str(item.get("trip") or item.get("name") or "").strip()
        for item in route.get("railways", [])
        if isinstance(item, dict) and str(item.get("trip") or item.get("name") or "").strip()
    ]
    if preference == "high_speed_rail" and not any(re.match(r"^G\d", trip.upper()) for trip in trips):
        return (
            "路线查询结果\n"
            f"{origin} → {destination}\n"
            "交通偏好：高铁\n"
            "当前地图路线观测没有返回 G 字头高铁车次；具体高铁车次请以铁路 12306 当日查询为准。"
        )

    lines = ["路线查询结果", f"{origin} → {destination}", f"交通方式：{mode}"]
    distance_km = route.get("distance_km") or distance.get("distance_km")
    if distance_km not in (None, ""):
        lines.append(f"距离：{distance_km} 公里")
    duration = route.get("duration_minutes") or distance.get("driving_duration_minutes")
    if duration not in (None, ""):
        lines.append(f"预计用时：{duration} 分钟")
    if route.get("cost") not in (None, ""):
        lines.append(f"参考费用：{route['cost']} 元")
    if route.get("transfers") not in (None, ""):
        lines.append(f"换乘次数：{route['transfers']} 次")
    if route.get("walking_distance_km") not in (None, ""):
        lines.append(f"步行接驳：约 {route['walking_distance_km']} 公里")

    if trips:
        lines.extend(["公共交通信息", f"参考线路：{'、'.join(trips[:3])}"])

    step_lines: list[str] = []
    for step in route.get("steps", [])[:4] if isinstance(route.get("steps"), list) else []:
        if not isinstance(step, dict):
            continue
        instruction = str(
            step.get("instruction")
            or step.get("road")
            or step.get("name")
            or ""
        ).strip()
        if instruction:
            step_lines.append(instruction[:120])
    if step_lines:
        lines.append("路线要点")
        lines.extend(f"- {item}" for item in step_lines)

    if route.get("error"):
        lines.extend(["查询提示", f"实时路线暂未获取成功：{route['error']}"])
    else:
        lines.extend(["出行提示", "距离和用时会随实时路况变化，出发前建议再次确认。"])
    return "\n".join(lines)


def rail_preference_matched(preference: str, trips: list[str]) -> bool | None:
    if not preference:
        return None
    codes = [trip.upper() for trip in trips]
    if preference == "high_speed_rail":
        return any(re.match(r"^G\d", code) for code in codes)
    if preference == "bullet_train":
        return any(re.match(r"^[GD]\d", code) for code in codes)
    if preference == "rail":
        return bool(codes)
    return None
