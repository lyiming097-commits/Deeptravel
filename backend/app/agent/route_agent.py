"""路线与交通 Agent：理解需求、选择工具并综合回答。"""

import asyncio
from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from backend.app.agent.base import AgentOutcome, SpecialistAgent, conversation_text
from backend.app.agent.intent import IntentDecision
from backend.app.agent.route_helpers import (
    KNOWN_CITIES,
    TRANSIT_KEYWORDS,
    clean_endpoint,
    contains_city,
    endpoint_city,
    extract_parameters,
    extract_train_date,
    first_train_code,
    is_cross_city,
    list_value,
    looks_like_local_landmark,
    mode_action,
    rail_preference_matched,
    railway_fallback,
    route_answer_fallback,
    today,
)
from backend.app.agent.route_workflows import (
    ask_train_date,
    run_cross_city_web,
    run_overview,
    run_railway,
)
from backend.app.tools import (
    AmapMcpTool,
    EvidenceItem,
    ItineraryMapTool,
    RailwayMcpTool,
    SemanticSearchResult,
    SemanticWebSearchTool,
)


class RouteState(TypedDict, total=False):
    message: str
    parameters: dict[str, Any]
    origin: str
    destination: str
    city: str
    travel_intent: str
    intent_source: str
    attempted: list[str]
    action: str
    route: dict[str, Any]
    distance: dict[str, Any]
    web_evidence: list[EvidenceItem]
    web_tools_used: list[str]
    cross_city: bool
    route_scope: str
    train_date: str
    tools_used: list[str]
    answer: str
    result: dict[str, Any]
    trace: list[dict[str, Any]]


class RoutePlanningAgent(SpecialistAgent):
    agent_name = "route-planning-agent"
    reasoning_mode = "react"
    role_description = "旅行路线与交通顾问"
    behavior_contract = (
        "理解用户的出行目标和交通偏好，用可用路线观测帮助用户做选择；"
        "偏好明确时优先尊重，问题含糊时才询问真正影响路线的信息。"
    )
    source_priority = (
        "跨城市铁路优先使用 12306 MCP 的当次车次、余票、票价、经停和换乘观测；"
        "城市内路线使用高德 MCP，并参考当次联网搜索；没有实时观测时不猜测路线事实。"
    )
    allowed_tools = frozenset({
        "route_transit", "route_driving", "route_walking", "distance_measure",
        "poi_search",
        "web_search", "web_fetch", "semantic_rerank", "railway_tickets",
        "railway_transfer", "railway_price", "railway_stops", "railway_stations",
        "railway_current_time",
    })
    known_cities = KNOWN_CITIES
    transit_keywords = TRANSIT_KEYWORDS

    def __init__(self, *args, amap_tool: AmapMcpTool,
                 web_tool: SemanticWebSearchTool | None = None,
                 railway_tool: RailwayMcpTool | None = None,
                 map_tool: ItineraryMapTool | None = None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.amap_tool, self.web_tool, self.railway_tool = amap_tool, web_tool, railway_tool
        self.map_tool = map_tool or ItineraryMapTool()
        graph = StateGraph(RouteState)
        graph.add_node("reason", self._reason)
        graph.add_node("act", self._act)
        graph.add_node("finalize", self._finalize)
        graph.add_edge(START, "reason")
        graph.add_conditional_edges("reason", self._next_step, {"act": "act", "finalize": "finalize"})
        graph.add_edge("act", "reason")
        graph.add_edge("finalize", END)
        self.graph = graph.compile()

    async def run(self, message: str, parameters: dict[str, Any]) -> AgentOutcome:
        context = conversation_text(message, parameters)
        parsed = extract_parameters(context)
        early_origin = str(parameters.get("origin") or parsed.get("origin") or "").strip()
        early_destination = str(parameters.get("destination") or parsed.get("destination") or "").strip()
        if early_origin and early_destination:
            # These endpoints are copied from the conversation; emit them
            # immediately while the model validates transport/date details.
            await self.emit_progress(f"起点：{early_origin}；终点：{early_destination}。")
        decision = await self.classify_intent(message, context)
        for source, target in (("origin", "origin"), ("target", "destination")):
            if not parsed.get(target) and decision.entities.get(source):
                parsed[target] = decision.entities[source]
        # The classifier already performs model-based entity extraction.  Map
        # its canonical transport value into the route workflow before asking
        # for a second, richer extraction pass.
        transport_mode = str(decision.entities.get("transport_mode") or "").strip()
        if transport_mode and transport_mode != "unknown":
            parsed.setdefault("transport_preference", transport_mode)
            parsed.setdefault("mode", transport_mode)
        train_date = extract_train_date(context, parameters)
        rail_request = any(
            word in context.lower()
            for word in ("高铁", "动车", "火车", "铁路", "列车", "车次", "余票", "经停", "换乘")
        )
        if rail_request and (
            not parsed.get("origin") or not parsed.get("destination") or not train_date
        ):
            parsed = await self._model_extract_route_parameters(context, parsed)
        origin = str(parameters.get("origin") or parsed.get("origin") or "").strip()
        destination = str(parameters.get("destination") or parsed.get("destination") or "").strip()
        if not origin or not destination:
            return await self._clarify(message, decision, parsed)
        # Emit only the normalized entities that passed model/rule validation.
        await self.emit_progress(f"起点：{origin}；终点：{destination}。")
        parsed.update({key: value for key, value in (("origin", origin), ("destination", destination)) if value})
        if not parsed.get("city"):
            parsed.pop("city", None)
        city = str(parameters.get("city") or parsed.get("city") or "").strip()
        effective = {**parsed, **parameters}
        # Re-evaluate after model extraction; relative dates are normalized to
        # YYYY-MM-DD and only values grounded in the original conversation are
        # accepted by the helper.
        train_date = extract_train_date(context, {**parameters, **parsed})
        scope = str(parsed.get("scope") or decision.entities.get("route_scope") or "unknown").lower()
        cross_city = await self.detect_cross_city(origin, destination, city, context, scope_hint=scope)
        preference = str(effective.get("transport_preference") or "")
        requested_mode = str(effective.get("mode") or "").lower()
        if cross_city and not preference and not requested_mode:
            return await run_overview(self, message, origin, destination, train_date, decision.intent, decision.source)
        if cross_city and preference in {"air", "flight", "plane"}:
            return await run_cross_city_web(self, message, origin, destination, decision.intent, decision.source, "飞机 航班 机票")
        railway_preference = preference in {"high_speed_rail", "bullet_train", "rail"}
        railway_default = not preference and requested_mode not in {"driving", "walking", "transit"}
        if cross_city and self.railway_tool and self.railway_tool.configured and (railway_preference or railway_default):
            if not train_date:
                return await ask_train_date(self, message, origin, destination, decision)
            if train_date < today().isoformat():
                return await ask_train_date(self, message, origin, destination, decision, f"你提供的日期 {train_date} 已经过期（当前日期为 {today().isoformat()}）。请改为未来的出发日期。")
            await self.emit_progress(f"出发日期：{train_date}。")
            return await run_railway(self, message, context, effective, origin, destination, train_date, decision.intent, decision.source)
        state = await self.graph.ainvoke(
            {"message": message, "parameters": effective, "origin": origin, "destination": destination,
             "city": city, "cross_city": cross_city, "route_scope": "cross_city" if cross_city else "city_internal",
             "train_date": train_date, "travel_intent": decision.intent, "intent_source": decision.source,
             "attempted": [], "tools_used": [], "web_evidence": [], "web_tools_used": [], "trace": []},
            config={"recursion_limit": self.settings.agent_graph_recursion_limit},
        )
        return AgentOutcome(
            answer=state["answer"], result=state["result"], tools_used=state.get("tools_used", state["attempted"]),
            citations=[self.amap_tool.citation("路线与距离查询", {"origin": origin, "destination": destination, "mode": state.get("route", {}).get("mode")}), *[item.citation() for item in state.get("web_evidence", [])]],
            agent_name=self.agent_name, reasoning_mode=self.reasoning_mode, execution_trace=state["trace"],
        )

    async def _model_extract_route_parameters(
        self, context: str, deterministic: dict[str, Any]
    ) -> dict[str, Any]:
        """Use the LLM to fill difficult railway arguments, then sanitize.

        The model is an interpreter, never the authority: locations must
        occur verbatim in the conversation and dates are normalized by the
        deterministic parser before reaching the 12306 MCP server.
        """
        fields = {"origin", "destination", "city", "mode", "transport_preference", "scope", "train_date"}
        model = await self.decide_json(
            "从旅行对话中提取 12306 查询所需参数，只返回 JSON。字段为 "
            "origin、destination、city、mode、transport_preference、scope、train_date。"
            "地点必须逐字出现在对话中，不得猜测或补全；优先提取车站名，其次提取城市名。"
            "transport_preference 只能为 high_speed_rail、bullet_train、rail、air、transit、"
            "driving、walking 或空字符串；scope 只能为 cross_city、city_internal 或 unknown。"
            "train_date 可以抄录用户说的日期或相对日期（如明天、2天后），没有明确日期则为空。",
            {"conversation": context, "deterministic_result": deterministic},
            deterministic,
        )
        if not isinstance(model, dict):
            return deterministic
        result = dict(deterministic)
        allowed = {
            "mode": {"transit", "driving", "walking", "air", "rail"},
            "transport_preference": {
                "high_speed_rail", "bullet_train", "rail", "air", "transit", "driving", "walking"
            },
            "scope": {"cross_city", "city_internal", "unknown"},
        }
        for key in fields - {"train_date", "origin", "destination", "city"}:
            value = str(model.get(key) or "").strip()
            if value and (key not in allowed or value in allowed[key]):
                result[key] = value
        for key in ("origin", "destination", "city"):
            value = str(model.get(key) or "").strip()
            # Sanitize model entities with the same deterministic endpoint
            # rules used by the regex parser.  A model may faithfully copy a
            # phrase such as “北京明天” from the conversation, but that is not
            # a valid 12306 station/city name.
            cleaned = clean_endpoint(value, key) if key in {"origin", "destination"} else value
            if cleaned and cleaned in context:
                result[key] = cleaned
        model_date = str(model.get("train_date") or "").strip()
        if model_date:
            normalized = extract_train_date(context, {"train_date": model_date})
            if normalized:
                result["train_date"] = normalized
        return result

    async def _clarify(self, message: str, decision: IntentDecision, parsed: dict[str, Any]) -> AgentOutcome:
        origin, destination = parsed.get("origin", ""), parsed.get("destination", "")
        missing = [name for name, value in (("起点", origin), ("终点", destination)) if not value]
        evidence: list[EvidenceItem] = []
        tools: list[str] = []
        if self.web_tool:
            try:
                result = await self.search_web(self.web_tool, message, intent="general", destination="")
                evidence, tools = result.items, result.tools_used
            except (RuntimeError, ValueError):
                pass
        answer = await self.compose_answer("路线信息还不完整时，亲切地询问缺少的字段，不要提供未经查询的具体路线。", {"missing": missing, "known": {"origin": origin, "destination": destination}, "web_evidence": self.evidence_for_model(evidence)}, f"没问题，请再告诉我{'和'.join(missing)}，我就能帮你规划合适的路线。")
        return AgentOutcome(answer=answer, result={"needs_clarification": True, "missing": missing, "travel_intent": decision.intent, "intent_source": decision.source}, tools_used=tools, citations=[item.citation() for item in evidence], agent_name=self.agent_name, reasoning_mode=self.reasoning_mode, execution_trace=[{"phase": "clarify", "missing": missing}])

    async def detect_cross_city(self, origin: str, destination: str, city: str, context: str, *, scope_hint: str = "unknown") -> bool:
        if is_cross_city(origin, destination, city, context):
            return True
        if scope_hint == "city_internal":
            return False
        if scope_hint == "cross_city" and not (looks_like_local_landmark(origin) or looks_like_local_landmark(destination)):
            return True
        if not self.railway_tool or not self.railway_tool.configured or (city and contains_city(origin, city) and contains_city(destination, city)):
            return False
        if looks_like_local_landmark(origin) or looks_like_local_landmark(destination):
            return False
        try:
            left, right = await asyncio.gather(self.railway_tool.stations(origin, limit=5), self.railway_tool.stations(destination, limit=5))
        except (RuntimeError, ValueError, OSError):
            return False
        return all(isinstance(value, dict) and any(isinstance(item, dict) and str(item.get("name") or "").strip() for item in value.get("stations", [])) for value in (left, right))

    async def _reason(self, state: RouteState) -> dict[str, Any]:
        route_tools = {"route_transit", "route_driving", "route_walking"}
        if not route_tools.intersection(state["attempted"]):
            requested = str(state["parameters"].get("mode", "")).lower()
            fallback = mode_action(requested or state["message"])
            if not requested and not self.settings.llm_mocked and self.llm.configured:
                fallback = str((await self.decide_json("只返回 JSON，从 route_transit、route_driving、route_walking 中选择用户明确要求的路线方式。", {"question": state["message"]}, {"action": fallback})).get("action", fallback))
            return {"action": fallback if fallback in route_tools else "route_transit"}
        if "distance_measure" not in state["attempted"]:
            return {"action": "distance_measure"}
        if self.web_tool and "web_search" not in state["attempted"]:
            return {"action": "web_search"}
        return {"action": "finish"}

    @staticmethod
    def _next_step(state: RouteState) -> Literal["act", "finalize"]:
        return "finalize" if state["action"] == "finish" else "act"

    async def _act(self, state: RouteState) -> dict[str, Any]:
        action = state["action"]
        self.check_tool(action)
        if action == "web_search":
            if not self.web_tool:
                return {"action": "finish"}
            try:
                result = await self.search_web(self.web_tool, f"{state['origin']} 到 {state['destination']} 交通 路线 最新信息", intent="general", destination="")
            except (RuntimeError, ValueError):
                result = SemanticSearchResult([], list(self.web_tool.tool_names))
            await self.emit_progress(f"已获得交通参考信息：{len(result.items)}条。")
            return {"attempted": [*state["attempted"], *result.tools_used], "tools_used": [*state["tools_used"], *result.tools_used], "web_evidence": result.items, "trace": [*state["trace"], {"phase": "action", "tool": action, "observation": {"pipeline": result.tools_used, "evidence_count": len(result.items)}}]}
        try:
            observation = await (self.amap_tool.distance(state["origin"], state["destination"], state["city"]) if action == "distance_measure" else self.amap_tool.route(action, state["origin"], state["destination"], state["city"]))
        except (RuntimeError, ValueError) as exc:
            observation = {"error": str(exc), "mode": action}
        if action.startswith("route_") and observation.get("mode") and not observation.get("error"):
            await self.emit_progress(f"交通方式：{observation['mode']}。")
        field = "distance" if action == "distance_measure" else "route"
        return {"attempted": [*state["attempted"], action], "tools_used": [*state["tools_used"], action], field: observation, "trace": [*state["trace"], {"phase": "action", "tool": action, "observation": {"mode": observation.get("mode"), "distance_km": observation.get("distance_km"), "duration_minutes": observation.get("duration_minutes")}}]}

    async def _finalize(self, state: RouteState) -> dict[str, Any]:
        route, distance, evidence = state.get("route", {}), state.get("distance", {}), state.get("web_evidence", [])
        result = {**route, "distance": distance, "cross_city": bool(state.get("cross_city")), "route_scope": "cross_city" if state.get("cross_city") else "city_internal", "train_date": state.get("train_date") or None, "travel_intent": state.get("travel_intent", "transportation"), "intent_source": state.get("intent_source", "rules"), "evidence_notes": [item.content for item in evidence]}
        result["map"] = {
            "provider": "OpenStreetMap",
            "mode": route.get("mode", ""),
            "points": self.map_tool.build_route_points(route, state["origin"], state["destination"]),
            "polyline": route.get("polyline") if isinstance(route.get("polyline"), list) else [],
            "polyline_source": route.get("polyline_source", "") if isinstance(route, dict) else "",
        }
        trips = [
            str(item.get("trip") or item.get("name") or "").strip()
            for item in route.get("railways", [])
            if isinstance(item, dict)
        ]
        preference = str(state["parameters"].get("transport_preference") or "")
        result["transport_preference"], result["preference_matched"] = preference or None, rail_preference_matched(preference, trips)
        fallback = route_answer_fallback(
            route,
            distance,
            state["origin"],
            state["destination"],
            preference,
        )
        model_route = {key: value for key, value in route.items() if key != "polyline"}
        model_result = {
            **result,
            "map": {**result["map"], "polyline": []},
        }
        answer = await self.compose_answer(
            "你是路线交通顾问。根据路线与距离观测灵活回答，尊重交通偏好，不编造实时信息，不输出链接列表。"
            "为了方便用户扫读，先用一行确认起点、终点和交通方式；再根据已有字段自然组织‘路线概览’、‘路线要点’、"
            "‘公共交通信息’或‘出行提示’等简短小标题。每个车次、路段或换乘建议单独分点，距离、用时、费用等字段分行展示；"
            "没有数据的字段和标题不要输出。内容简单时保持简洁，不要为了套模板重复用户问题。",
            {"question": state["message"], "observations": {"route": model_route, "distance": distance, "web_evidence": self.evidence_for_model(evidence)}, "result": model_result},
            fallback,
        )
        return {"answer": answer, "result": result, "trace": [*state["trace"], {"phase": "final", "status": "completed"}]}

    @staticmethod
    def _map_points(
        route: dict[str, Any], origin: str, destination: str
    ) -> list[dict[str, Any]]:
        """Backward-compatible delegate; route map shaping lives in a tool."""
        return ItineraryMapTool.build_route_points(route, origin, destination)

    # Keep the former private workflow entry points for integrations that
    # invoked them directly before the workflow split.
    async def _ask_train_date(self, message: str, origin: str, destination: str, decision: IntentDecision, reason: str = "") -> AgentOutcome:
        return await ask_train_date(self, message, origin, destination, decision, reason)

    async def _run_cross_city_web(self, message: str, origin: str, destination: str, travel_intent: str, intent_source: str, *, query_hint: str) -> AgentOutcome:
        return await run_cross_city_web(self, message, origin, destination, travel_intent, intent_source, query_hint)

    async def _run_railway(self, *, message: str, context: str, parameters: dict[str, Any], origin: str, destination: str, train_date: str, travel_intent: str, intent_source: str) -> AgentOutcome:
        return await run_railway(self, message, context, parameters, origin, destination, train_date, travel_intent, intent_source)

    async def _run_cross_city_overview(self, *, message: str, origin: str, destination: str, train_date: str, travel_intent: str, intent_source: str) -> AgentOutcome:
        return await run_overview(self, message, origin, destination, train_date, travel_intent, intent_source)

    extract_parameters = staticmethod(extract_parameters)
    extract_train_date = staticmethod(extract_train_date)
    is_cross_city = staticmethod(is_cross_city)
    _today = staticmethod(today)
    _mode_action = staticmethod(mode_action)
    _list_value = staticmethod(list_value)
    _first_train_code = staticmethod(first_train_code)
    _railway_fallback = staticmethod(railway_fallback)
    _rail_preference_matched = staticmethod(rail_preference_matched)
    _endpoint_city = staticmethod(endpoint_city)
    _contains_city = staticmethod(contains_city)
    _looks_like_local_landmark = staticmethod(looks_like_local_landmark)
