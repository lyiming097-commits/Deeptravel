"""跨城路线工作流，和路线 Agent 的图编排分离。"""

import asyncio
from typing import Any

from backend.app.agent.base import AgentOutcome
from backend.app.agent.intent import IntentDecision
from backend.app.agent.route_helpers import (
    clean_railway_station_query,
    first_train_code,
    list_value,
    railway_fallback,
    select_train_samples,
)
from backend.app.tools import ItineraryMapTool, SemanticSearchResult


def route_map_points_from_observation(
    route: dict[str, Any], origin: str, destination: str
) -> list[dict[str, str]]:
    """Backward-compatible delegate for route map point shaping."""
    return ItineraryMapTool.build_route_points(route, origin, destination)


async def resolve_route_map_points(
    agent: Any, origin: str, destination: str
) -> list[dict[str, str]]:
    """Resolve cross-city endpoints for the route map when needed.

    Railway and flight observations do not contain geographic coordinates.
    Ask the already injected Amap tool to resolve those two endpoint entities;
    return an empty list when the map provider is mocked or unavailable so a
    route answer is never blocked by optional map enrichment.
    """

    try:
        agent.check_tool("poi_search")
    except (AttributeError, RuntimeError):
        return []
    map_tool = getattr(agent, "map_tool", None) or ItineraryMapTool()
    return await map_tool.resolve_route_points(
        getattr(agent, "amap_tool", None), origin, destination
    )


async def resolve_railway_station(tool: Any, value: str) -> str:
    """Resolve a user place into the exact station name known by 12306."""

    query = clean_railway_station_query(value)
    if not query:
        raise ValueError("车站名称为空")
    result = await tool.stations(query, limit=10)
    stations = list_value(result, "stations")
    names = [str(item.get("name") or "").strip() for item in stations]
    names = [name for name in names if name]
    if not names:
        error = str(result.get("error") or "") if isinstance(result, dict) else ""
        raise ValueError(error or f"未识别到车站：{value}")
    # City names such as 郑州 should resolve to the exact city station first;
    # explicit directional names such as 郑州东 still match exactly.  Only
    # fall back to the provider's ranked first result when no exact name is
    # present.
    return next((name for name in names if name == query), names[0])


async def ask_train_date(
    agent: Any, message: str, origin: str, destination: str, decision: IntentDecision, reason: str = ""
) -> AgentOutcome:
    answer = await agent.compose_answer(
        "用户要查询跨城市铁路出行，但日期信息不可用。亲切地说明原因并请用户提供未来日期；"
        "日期可以是 YYYY-MM-DD 或‘明天/后天’，不要自行猜测日期和车次。",
        {"question": message, "origin": origin, "destination": destination, "reason": reason},
        reason or f"可以帮你查 {origin} 到 {destination} 的高铁、动车和普铁。请告诉我计划出发的日期（例如 2026-09-01），我再为你查询车次和余票。",
    )
    missing = [] if reason else ["出发日期"]
    return AgentOutcome(
        answer=answer,
        result={"needs_clarification": True, "missing": missing, "date_error": reason or None,
                "origin": origin, "destination": destination, "cross_city": True,
                "route_scope": "cross_city", "travel_intent": decision.intent,
                "intent_source": decision.source},
        agent_name=agent.agent_name, reasoning_mode=agent.reasoning_mode,
        execution_trace=[{"phase": "clarify", "missing": missing, "date_error": reason or None, "cross_city": True}],
    )


async def run_cross_city_web(
    agent: Any, message: str, origin: str, destination: str, travel_intent: str,
    intent_source: str, query_hint: str,
) -> AgentOutcome:
    evidence: list[Any] = []
    tools: list[str] = []
    if agent.web_tool:
        try:
            for name in agent.web_tool.tool_names:
                agent.check_tool(name)
            result = await agent.search_web(agent.web_tool, f"{origin} 到 {destination} {query_hint} 最新出行信息", intent="general", destination="")
            evidence, tools = result.items, result.tools_used
        except (RuntimeError, ValueError):
            pass
    map_points = await resolve_route_map_points(agent, origin, destination)
    if map_points:
        tools.append("poi_search")
    answer = await agent.compose_answer(
        "用户明确询问跨城市非铁路出行。根据抓取后的网页正文回答，只引用证据中出现的信息，"
        "不编造班次、价格和时刻，不要输出 URL 或链接列表。"
        "回答先确认起点和终点，再按可核实的出行方式分段；每种方式单独写清适用场景、"
        "观测到的时长或价格，最后给出简短的核实提示。没有对应证据的方式不要硬凑段落。",
        {"question": message, "origin": origin, "destination": destination, "web_evidence": agent.evidence_for_model(evidence)},
        f"我已记录你的跨城出行：{origin} → {destination}。目前没有可用的实时航班数据，请补充出发日期，我再继续核实。",
    )
    return AgentOutcome(
        answer=answer,
        result={"query_type": "cross_city_web", "origin": origin, "destination": destination,
                "cross_city": True, "route_scope": "cross_city", "travel_intent": travel_intent,
                "intent_source": intent_source, "evidence_notes": [item.content for item in evidence],
                "map": {"provider": "OpenStreetMap", "points": map_points, "polyline": []}},
        tools_used=list(dict.fromkeys(tools)),
        citations=([agent.amap_tool.citation("路线地图定位", {"origin": origin, "destination": destination})] if map_points else [])
        + [item.citation() for item in evidence], agent_name=agent.agent_name,
        reasoning_mode=agent.reasoning_mode,
        execution_trace=[{"phase": "action", "tool": "web_search", "observation": {"pipeline": tools, "evidence_count": len(evidence)}}],
    )


async def run_railway(
    agent: Any, message: str, context: str, parameters: dict[str, Any], origin: str,
    destination: str, train_date: str, travel_intent: str, intent_source: str,
) -> AgentOutcome:
    tool = agent.railway_tool
    if not tool:
        raise RuntimeError("12306 MCP 工具未注入")
    tools_used = ["railway_stations", "railway_tickets"]
    railway_origin = clean_railway_station_query(origin)
    railway_destination = clean_railway_station_query(destination)
    try:
        railway_origin, railway_destination = await asyncio.gather(
            resolve_railway_station(tool, origin),
            resolve_railway_station(tool, destination),
        )
        raw = await tool.tickets(railway_origin, railway_destination, train_date)
    except (RuntimeError, ValueError) as exc:
        raw = {"success": False, "error": str(exc), "trains": []}
    citations = [tool.citation("车次与余票查询", {
        "origin": origin, "destination": destination, "from_station": railway_origin,
        "to_station": railway_destination, "train_date": train_date,
    })]
    all_trains = list_value(raw, "trains")
    limit = max(1, min(int(agent.settings.railway_result_limit), 50))
    trains = select_train_samples(all_trains, limit, f"{context} {message}")
    tickets = {**raw, "trains": trains, "count": len(all_trains), "returned_count": len(trains), "truncated": len(all_trains) > len(trains)}
    await agent.emit_progress("交通方式：铁路（12306）。")
    await agent.emit_progress(f"已查询到直达车次：{len(all_trains)}趟。")
    text = f"{context}\n{message}".lower()
    wants_transfer = any(x in text for x in ("中转", "换乘", "转车", "接续"))
    wants_stops = any(x in text for x in ("经停", "停靠", "途经", "停站"))
    wants_price = any(x in text for x in ("票价", "价格", "多少钱", "费用"))
    transfers: dict[str, Any] = {"transfers": []}
    if wants_transfer or not all_trains:
        tools_used.append("railway_transfer")
        try:
            transfers = await tool.transfers(railway_origin, railway_destination, train_date)
        except (RuntimeError, ValueError) as exc:
            transfers = {"transfers": [], "error": str(exc)}
        citations.append(tool.citation("中转换乘查询", {"origin": origin, "destination": destination, "train_date": train_date}))
        await agent.emit_progress(f"已找到中转换乘方案：{len(list_value(transfers, 'transfers'))}个。")
    prices: dict[str, Any] = {"data": []}
    if wants_price:
        tools_used.append("railway_price")
        try:
            prices = await tool.prices(
                railway_origin, railway_destination, train_date, first_train_code(trains)
            )
        except (RuntimeError, ValueError) as exc:
            prices = {"data": [], "error": str(exc)}
        citations.append(tool.citation("票价查询", {"origin": origin, "destination": destination, "train_date": train_date}))
    stops: dict[str, Any] = {"stations": []}
    code = first_train_code(trains)
    if wants_stops and code:
        tools_used.append("railway_stops")
        try:
            stops = await tool.stops(
                code, railway_origin, railway_destination, train_date
            )
        except (RuntimeError, ValueError) as exc:
            stops = {"stations": [], "error": str(exc)}
        citations.append(tool.citation("经停站查询", {"train_no": code, "origin": origin, "destination": destination, "train_date": train_date}))
        await agent.emit_progress(f"已获取 {code} 经停站：{len(list_value(stops, 'stations'))}站。")
    evidence: list[Any] = []
    if agent.web_tool:
        try:
            for name in agent.web_tool.tool_names:
                agent.check_tool(name)
            web = await agent.search_web(agent.web_tool, f"{origin} 到 {destination} {train_date} 高铁 动车 普铁 航班 出行信息", intent="general", destination="")
            evidence = web.items
            tools_used.extend(web.tools_used)
            citations.extend(item.citation() for item in evidence)
        except (RuntimeError, ValueError):
            pass
    map_points = await resolve_route_map_points(agent, origin, destination)
    if map_points:
        tools_used.append("poi_search")
        citations.append(agent.amap_tool.citation("路线地图定位", {"origin": origin, "destination": destination}))
    result = {"query_type": "railway", "origin": origin, "destination": destination, "train_date": train_date,
              "railway_from_station": railway_origin, "railway_to_station": railway_destination,
              "cross_city": True, "route_scope": "cross_city", "railway": tickets,
              "total_trains": len(all_trains), "returned_trains": len(trains), "trains_truncated": len(all_trains) > len(trains),
              "trains": trains, "transfers": list_value(transfers, "transfers"), "prices": list_value(prices, "data"),
              "stops": list_value(stops, "stations"), "evidence_notes": [item.content for item in evidence],
              "travel_intent": travel_intent, "intent_source": intent_source,
              "map": {"provider": "OpenStreetMap", "points": map_points,
                      "mode": "",
                      "polyline": []}}
    answer = await agent.compose_answer(
        "你是跨城市铁路出行顾问。直接回答用户问题，综合 12306 MCP 的车次、余票、票价、经停站和换乘观测。"
        "只把观测中明确出现的内容告诉用户，不编造事实，不要输出 URL 或链接列表。"
        "为了让车次信息容易比较，先单独显示‘铁路车次查询结果’、起终点和出发日期，"
        "再用分点逐条列出有限数量的车次；有票价、余票、经停站或换乘数据时再分别增加对应小节。"
        "没有数据的字段不要写‘未知’，不要输出空小节；结尾可用一句话提示实时信息以 12306 为准。",
        {"question": message, "result": result, "observations": {"tickets": tickets, "transfers": transfers, "prices": prices, "stops": stops, "web_evidence": agent.evidence_for_model(evidence)}},
        railway_fallback(result),
    )
    return AgentOutcome(answer=answer, result=result, tools_used=list(dict.fromkeys(tools_used)), citations=citations,
                        agent_name=agent.agent_name, reasoning_mode=agent.reasoning_mode,
                        execution_trace=[{"phase": "final", "status": "completed"}])


async def run_overview(
    agent: Any, message: str, origin: str, destination: str, train_date: str,
    travel_intent: str, intent_source: str,
) -> AgentOutcome:
    async def rail() -> dict[str, Any]:
        if not agent.railway_tool or not agent.railway_tool.configured or not train_date or train_date < agent._today().isoformat():
            return {"trains": [], "unavailable_reason": "past_date" if train_date and train_date < agent._today().isoformat() else "missing_date_or_endpoint"}
        try:
            rail_origin, rail_destination = await asyncio.gather(
                resolve_railway_station(agent.railway_tool, origin),
                resolve_railway_station(agent.railway_tool, destination),
            )
            result = await agent.railway_tool.tickets(
                rail_origin, rail_destination, train_date
            )
            return {
                **result,
                "railway_from_station": rail_origin,
                "railway_to_station": rail_destination,
            }
        except (RuntimeError, ValueError) as exc:
            return {"trains": [], "error": str(exc)}
    async def drive() -> dict[str, Any]:
        try:
            return await agent.amap_tool.route("route_driving", origin, destination, "")
        except (RuntimeError, ValueError) as exc:
            return {"error": str(exc), "mode": "驾车"}
    async def web() -> SemanticSearchResult:
        if not agent.web_tool:
            return SemanticSearchResult([], [])
        try:
            for name in agent.web_tool.tool_names:
                agent.check_tool(name)
            return await agent.search_web(agent.web_tool, f"{origin} 到 {destination} 飞机 航班 高铁 火车 自驾 出行方案", intent="general", destination="")
        except (RuntimeError, ValueError):
            return SemanticSearchResult([], list(agent.web_tool.tool_names))
    railway, driving, web_result = await asyncio.gather(rail(), drive(), web())
    map_points = route_map_points_from_observation(driving, origin, destination)
    if not map_points:
        map_points = await resolve_route_map_points(agent, origin, destination)
    all_trains = list_value(railway, "trains")
    trains = select_train_samples(
        all_trains,
        max(1, min(int(agent.settings.railway_result_limit), 50)),
        message,
    )
    evidence = web_result.items[:3]
    result = {"query_type": "cross_city_overview", "route_scope": "cross_city", "cross_city": True,
              "origin": origin, "destination": destination, "train_date": train_date or None,
              "railway": {**railway, "trains": trains, "count": len(all_trains), "returned_count": len(trains), "truncated": len(all_trains) > len(trains)},
              "total_trains": len(all_trains), "returned_trains": len(trains), "trains": trains,
              "driving": driving, "flight_evidence": [item.content for item in evidence],
              "travel_intent": travel_intent, "intent_source": intent_source,
              "map": {"provider": "OpenStreetMap", "points": map_points,
                      "mode": "驾车" if driving and not driving.get("error") else "",
                      "polyline": driving.get("polyline", []) if isinstance(driving, dict) else [],
                      "polyline_source": driving.get("polyline_source", "") if isinstance(driving, dict) else ""}}
    tools = (["railway_tickets"] if agent.railway_tool and agent.railway_tool.configured and train_date else [])
    if not driving.get("error"): tools.append("route_driving")
    tools.extend(web_result.tools_used)
    citations = []
    if tools and "railway_tickets" in tools:
        citations.append(agent.railway_tool.citation("车次与余票查询", {"origin": origin, "destination": destination, "train_date": train_date}))
    if not driving.get("error"):
        citations.append(agent.amap_tool.citation("驾车路线查询", {"origin": origin, "destination": destination}))
    if map_points and driving.get("error"):
        tools.append("poi_search")
        citations.append(agent.amap_tool.citation("路线地图定位", {"origin": origin, "destination": destination}))
    citations.extend(item.citation() for item in evidence)
    fallback = ["出行方案对比", f"{origin} → {destination}"]
    if train_date:
        fallback.append(f"出发日期：{train_date}")
    fallback.append("铁路")
    if all_trains:
        fallback.append(f"查到 {len(all_trains)} 趟车次，先列出 {len(trains)} 趟。")
    elif railway.get("unavailable_reason") == "past_date":
        fallback.append(f"{train_date} 已经过期，请提供未来日期。")
    else:
        fallback.append("需要出发日期后才能查询实时车次和余票。")
    if not driving.get("error"):
        fallback.extend([
            "驾车",
            f"约 {driving.get('distance_km', '未知')} 公里，预计 {driving.get('duration_minutes', '未知')} 分钟。",
        ])
    fallback.extend([
        "飞机",
        "已找到几条相关公开信息，具体航班和价格请以航空公司实时页面为准。"
        if evidence
        else "暂未获得可核实的公开航班信息。",
        "出行提示",
        "不同交通方式的班次、价格和用时会变化，出发前请再次确认。",
    ])
    model_driving = {
        key: value for key, value in driving.items() if key != "polyline"
    }
    model_result = {
        **result,
        "map": {**result["map"], "polyline": []},
    }
    answer = await agent.compose_answer(
        "你是跨城市出行顾问。用户没有指定交通方式，请分别比较铁路、驾车和飞机信息，每种方式最多列出三条经过观测的数据。"
        "铁路只能使用 12306 数据，驾车只能使用地图观测，飞机只能归纳网页正文，不要输出链接或编造实时数据。"
        "回答先单独确认起点、终点和日期（有日期才显示），随后按‘铁路’、‘驾车’、‘飞机’自然分段；"
        "每种方式的车次、距离、用时和限制条件分行或分点展示，最后补充简短的‘出行提示’。"
        "没有观测到的字段不要编造，也不要输出空标题或内部工具名称。",
        {"question": message, "result": model_result, "observations": {"railway": result["railway"], "driving": model_driving, "flight_web_evidence": agent.evidence_for_model(evidence)}},
        "\n".join(fallback),
    )
    return AgentOutcome(answer=answer, result=result, tools_used=list(dict.fromkeys(tools)), citations=citations,
                        agent_name=agent.agent_name, reasoning_mode=agent.reasoning_mode,
                        execution_trace=[{"phase": "final", "status": "completed"}])
