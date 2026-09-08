from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Scene:
    code: str
    name: str
    description: str
    welcome_message: str
    allowed_tools: tuple[str, ...]


SCENES = {
    "TRAVEL_PLAN": Scene(
        "TRAVEL_PLAN",
        "AI 行程规划",
        "理解旅行意图，结合证据灵活规划行程、住宿与当地体验",
        "你好，很高兴陪你规划旅程！我是你的 AI 旅行顾问，可以帮你安排每天去哪里、怎么玩，也可以帮你找住宿、了解当地体验。你可以直接说“想去杭州玩两天”，也可以先问“西湖附近有哪些酒店”，我们从你此刻最关心的事情开始。",
        (
            "rag_search",
            "web_search",
            "web_fetch",
            "semantic_rerank",
            "poi_search",
            "weather_query",
        ),
    ),
    "POI_DISCOVERY": Scene(
        "POI_DISCOVERY",
        "景点查询",
        "ReAct 检索知识库、高德 MCP 与外部网页",
        "你好呀！我是你的景点与本地体验顾问，可以陪你发现值得去的景点、博物馆、公园、美食和小众体验。你可以告诉我目的地、喜欢的类型、同行人和游玩时间，也可以直接问“这座城市有什么好玩的”，我会按你的兴趣来推荐。",
        (
            "rag_search",
            "poi_search",
            "web_search",
            "web_fetch",
            "semantic_rerank",
        ),
    ),
    "ROUTE_PLANNING": Scene(
        "ROUTE_PLANNING",
        "路线交通规划",
        "ReAct 选择公交、驾车或步行并结合联网信息查询距离",
        "你好！我是你的旅行路线与交通顾问，可以帮你安排公交、驾车、步行等出行方式，也能查询跨城市的列车班次和余票，让每一段路程都更方便、更从容。告诉我起点、终点和出发日期即可，如果有偏好的出行方式也可以一并告诉我，不必担心一次说得很完整。",
        (
            "distance_measure",
            "route_walking",
            "route_driving",
            "route_transit",
            "poi_search",
            "railway_tickets",
            "railway_transfer",
            "railway_price",
            "railway_stops",
            "railway_stations",
            "railway_current_time",
            "web_search",
            "web_fetch",
            "semantic_rerank",
        ),
    ),
    "BUDGET_ESTIMATION": Scene(
        "BUDGET_ESTIMATION",
        "费用估算",
        "Reflection 校验费用并参考联网价格信息",
        "你好，我是你的旅行预算顾问，会帮你把住宿、餐饮、交通、门票和机动费用梳理得清清楚楚，让旅途既舒心又心里有数。你可以告诉我打算去哪里、出行几天、几个人以及预算大概在什么范围，也可以先问一个具体花费，我会根据你的计划慢慢补充。",
        (
            "budget_calculator",
            "budget_validator",
            "web_search",
            "web_fetch",
            "semantic_rerank",
        ),
    ),
}


def list_scenes() -> list[dict]:
    return [asdict(scene) for scene in SCENES.values()]


def get_scene(code: str | None) -> Scene:
    return SCENES.get((code or "TRAVEL_PLAN").upper(), SCENES["TRAVEL_PLAN"])
