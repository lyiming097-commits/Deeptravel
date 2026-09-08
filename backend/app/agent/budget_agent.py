import re
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from backend.app.agent.base import AgentOutcome, SpecialistAgent, conversation_text
from backend.app.tools import EvidenceItem, SemanticWebSearchTool


class BudgetState(TypedDict, total=False):
    message: str
    parameters: dict[str, Any]
    draft: dict[str, Any]
    reflection: dict[str, Any]
    web_evidence: list[EvidenceItem]
    tools_used: list[str]
    result: dict[str, Any]
    travel_intent: str
    intent_source: str
    answer: str
    trace: list[dict[str, Any]]


class BudgetEstimationAgent(SpecialistAgent):
    agent_name = "budget-estimation-agent"
    reasoning_mode = "reflection"
    role_description = "旅行预算与费用风险顾问"
    behavior_contract = (
        "你是一位会和用户一起把费用想清楚的旅行预算顾问。"
        "根据用户给出的计划和问题灵活解释总额、分项、假设与风险；需要计算时使用确定性计算，"
        "再进行 Reflection 复核，不把没有提供的金额当成事实。"
    )
    source_priority = (
        "以用户明确说明的数字和确定性计算结果为基础，再用 Reflection 检查算术、漏项和风险；"
        "同时参考当次联网搜索中的价格与政策信息；实时价格只有在获得可靠观测时才引用，"
        "否则标注为估算"
    )
    allowed_tools = frozenset(
        {
            "budget_calculator",
            "budget_validator",
            "web_search",
            "web_fetch",
            "semantic_rerank",
        }
    )

    def __init__(
        self,
        *args,
        web_tool: SemanticWebSearchTool | None = None,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.web_tool = web_tool
        graph = StateGraph(BudgetState)
        graph.add_node("draft", self._draft)
        graph.add_node("reflect", self._reflect)
        graph.add_node("revise", self._revise)
        graph.add_edge(START, "draft")
        graph.add_edge("draft", "reflect")
        graph.add_edge("reflect", "revise")
        graph.add_edge("revise", END)
        self.graph = graph.compile()

    async def run(self, message: str, parameters: dict[str, Any]) -> AgentOutcome:
        context = conversation_text(message, parameters)
        early_parameters = self.normalize_parameters(
            {**self.extract_parameters(context), **parameters}
        )
        early_budget_complete = (
            "days" in early_parameters
            and "people" in early_parameters
            and ("daily_budget" in early_parameters or "total_budget" in early_parameters)
        )
        early_fact_emitted = False
        if early_budget_complete:
            budget_value = early_parameters.get("total_budget")
            budget_label = (
                f"总预算：{budget_value}元"
                if budget_value is not None
                else f"每人每天预算：{early_parameters['daily_budget']}元"
            )
            await self.emit_progress(
                f"天数：{early_parameters['days']}天；人数：{early_parameters['people']}人；{budget_label}。"
            )
            early_fact_emitted = True
        intent_decision = await self.classify_intent(message, context)
        fallback = self.extract_parameters(context)
        complete_fallback = (
            "days" in fallback
            and "people" in fallback
            and ("daily_budget" in fallback or "total_budget" in fallback)
        )
        parsed = (
            fallback
            if complete_fallback
            else await self.decide_json(
                "从自然语言旅行对话中提取预算需求，只返回 days、people、"
                "daily_budget、total_budget 四个字段的JSON。没有明确提到的字段不要返回，"
                "不得猜测；daily_budget 表示每人每天预算，total_budget 表示整趟总预算。",
                {"conversation": context, "deterministic_result": fallback},
                fallback,
            )
        )
        effective_parameters = self.normalize_parameters(
            {
                **fallback,
                **parsed,
                **parameters,
                "_travel_intent": intent_decision.intent,
                "_intent_source": intent_decision.source,
            }
        )
        missing = [
            label
            for label, keys in (
                ("天数", ("days",)),
                ("人数", ("people",)),
                ("预算（总预算或每人每日预算）", ("daily_budget", "total_budget")),
            )
            if not any(key in effective_parameters for key in keys)
        ]
        if missing:
            web_evidence: list[EvidenceItem] = []
            web_tools: list[str] = []
            if self.web_tool:
                try:
                    for tool_name in self.web_tool.tool_names:
                        self.check_tool(tool_name)
                    search_result = await self.search_web(
                        self.web_tool,
                        context, intent="general", destination=""
                    )
                    web_evidence = search_result.items
                    web_tools = search_result.tools_used
                except (RuntimeError, ValueError):
                    web_evidence = []
            answer = await self.compose_answer(
                "用户的预算信息不完整。亲切地询问缺少的数字，说明可以一次告诉我，"
                "也可以分几次补充；可以参考联网证据，但不要自行假定金额。",
                {
                    "missing": missing,
                    "conversation": context,
                    "web_evidence": self.evidence_for_model(web_evidence),
                },
                f"当然可以！为了帮你算得更贴合实际，还想知道你的{'、'.join(missing)}。"
                "比如可以说“成都 5 天 2 人，每人每天 600 元”，分开告诉我也没关系。",
            )
            return AgentOutcome(
                answer=answer,
                result={
                    "needs_clarification": True,
                    "missing": missing,
                    "travel_intent": intent_decision.intent,
                    "intent_source": intent_decision.source,
                },
                tools_used=web_tools,
                citations=[item.citation() for item in web_evidence],
                agent_name=self.agent_name,
                reasoning_mode=self.reasoning_mode,
                execution_trace=[
                    {"phase": "clarify", "missing": missing},
                    {
                        "phase": "action",
                        "tool": "web_search",
                        "observation": {
                            "pipeline": web_tools,
                            "evidence_count": len(web_evidence),
                        },
                    },
                ],
            )
        budget_value = effective_parameters.get("total_budget")
        if budget_value is None:
            budget_value = effective_parameters.get("daily_budget")
            budget_label = f"每人每天预算：{budget_value}元"
        else:
            budget_label = f"总预算：{budget_value}元"
        if not early_fact_emitted:
            await self.emit_progress(
                f"天数：{effective_parameters['days']}天；人数：{effective_parameters['people']}人；{budget_label}。"
            )
        state = await self.graph.ainvoke(
            {
                "message": message,
                "parameters": effective_parameters,
                "trace": [],
                "tools_used": [],
                "web_evidence": [],
            },
            config={"recursion_limit": self.settings.agent_graph_recursion_limit},
        )
        return AgentOutcome(
            answer=state["answer"],
            result=state["result"],
            tools_used=state.get("tools_used", ["budget_calculator", "budget_validator"]),
            citations=[item.citation() for item in state.get("web_evidence", [])],
            agent_name=self.agent_name,
            reasoning_mode=self.reasoning_mode,
            execution_trace=state["trace"],
        )

    async def _draft(self, state: BudgetState) -> dict[str, Any]:
        self.check_tool("budget_calculator")
        parameters = state["parameters"]
        days = max(1, min(int(parameters["days"]), 30))
        people = max(1, min(int(parameters["people"]), 20))
        if "total_budget" in parameters:
            total = max(0.0, round(float(parameters["total_budget"]), 2))
            daily_budget = round(total / days / people, 2)
        else:
            daily_budget = max(0.0, float(parameters["daily_budget"]))
            total = round(days * people * daily_budget, 2)
        draft = self.calculate_breakdown(total, days, people, daily_budget)
        await self.emit_progress(f"按已提供条件估算总额：{total:.2f}元。")
        return {
            "draft": draft,
            "tools_used": [*state.get("tools_used", []), "budget_calculator"],
            "trace": [
                *state["trace"],
                {"phase": "draft", "tool": "budget_calculator", "total": total},
            ],
        }

    async def _reflect(self, state: BudgetState) -> dict[str, Any]:
        self.check_tool("budget_validator")
        draft = state["draft"]
        categories_total = round(sum(draft["breakdown"].values()), 2)
        fallback = {
            "valid": categories_total == draft["estimated_total"],
            "issues": []
            if categories_total == draft["estimated_total"]
            else ["分项金额与总额不一致"],
            "advice": "保留 10% 机动预算，实际交通和门票以实时价格为准。",
        }
        reflection = await self.decide_json(
            "你是旅行预算审核器。检查算术、漏项和风险，只返回JSON，"
            "格式为 valid(bool), issues(array), advice(string)。不要修改用户输入。",
            {"request": state["message"], "draft": draft},
            fallback,
        )
        return {
            "reflection": reflection,
            "tools_used": [*state.get("tools_used", []), "budget_validator"],
            "trace": [
                *state["trace"],
                {
                    "phase": "reflection",
                    "tool": "budget_validator",
                    "valid": bool(reflection.get("valid", fallback["valid"])),
                    "issue_count": len(reflection.get("issues", [])),
                },
            ],
        }

    async def _revise(self, state: BudgetState) -> dict[str, Any]:
        draft = state["draft"]
        web_evidence: list[EvidenceItem] = []
        web_tools: list[str] = []
        if self.web_tool:
            try:
                for tool_name in self.web_tool.tool_names:
                    self.check_tool(tool_name)
                query = f"{state['message']} 旅行费用 预算 价格 信息"
                search_result = await self.search_web(
                    self.web_tool,
                    query, intent="general", destination=""
                )
                web_evidence = search_result.items
                web_tools = search_result.tools_used
            except (RuntimeError, ValueError):
                web_evidence = []
        result = {
            **draft,
            "review": state["reflection"],
            "travel_intent": state["parameters"].get(
                "_travel_intent", "budget"
            ),
            "intent_source": state["parameters"].get("_intent_source", "rules"),
            "evidence_notes": [item.content for item in web_evidence],
        }
        tools_used = list(dict.fromkeys([*state.get("tools_used", []), *web_tools]))
        answer = await self.compose_answer(
            "你是旅行预算顾问。结合用户原问题、计算草案和 Reflection 结果，"
            "自行选择清晰、亲切的表达方式说明数字、假设和风险，不套固定模板。"
            "明确哪些是估算，不得篡改已校验数字或编造实时价格。"
            "可以参考联网证据中的价格信息并说明时效性；请消化网页正文，"
            "不要输出原始 URL、Markdown 链接或链接列表。",
            {
                "question": state["message"],
                "draft": draft,
                "reflection": state["reflection"],
                "web_evidence": self.evidence_for_model(web_evidence),
                "result": result,
            },
            f"预计总预算 {draft['estimated_total']:.2f} 元，"
            f"含 {draft['breakdown']['buffer']:.2f} 元机动费用。",
        )
        return {
            "result": result,
            "web_evidence": web_evidence,
            "tools_used": tools_used,
            "answer": answer,
            "trace": [*state["trace"], {"phase": "revise", "status": "completed"}],
        }

    @staticmethod
    def calculate_breakdown(
        total: float, days: int, people: int, daily_budget: float
    ) -> dict[str, Any]:
        accommodation = round(total * 0.35, 2)
        food = round(total * 0.25, 2)
        transport = round(total * 0.15, 2)
        tickets = round(total * 0.15, 2)
        buffer = round(total - accommodation - food - transport - tickets, 2)
        return {
            "days": days,
            "people": people,
            "daily_budget": daily_budget,
            "estimated_total": total,
            "currency": "CNY",
            "breakdown": {
                "accommodation": accommodation,
                "food": food,
                "transport": transport,
                "tickets": tickets,
                "buffer": buffer,
            },
        }

    @staticmethod
    def extract_parameters(message: str) -> dict[str, float | int]:
        """Parse common Chinese budget phrases from a free-form chat turn."""
        text = " ".join(message.split())

        def number(value: str) -> float:
            value = value.replace(",", "").replace("，", "").strip()
            if value.isdigit() or re.fullmatch(r"\d+(?:\.\d+)?", value):
                return float(value)
            return float(BudgetEstimationAgent._chinese_number(value))

        def capture(patterns: tuple[str, ...]) -> float | None:
            for pattern in patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    try:
                        return number(match.group(1))
                    except (TypeError, ValueError):
                        continue
            return None

        parsed: dict[str, float | int] = {}
        days = capture((r"([0-9]+(?:\.[0-9]+)?|[零一二两三四五六七八九十百]+)\s*(?:天|日)",))
        people = capture(
            (
                r"([0-9]+|[零一二两三四五六七八九十百]+)\s*(?:个\s*)?(?:成年人|成人|人|位|名)",
            )
        )
        daily = capture(
            (
                r"(?:每人每天|每天每人|人均每天|每人每日|每日每人)\s*(?:约|大约|预算)?\s*[¥￥]?\s*([0-9]+(?:[,，][0-9]{3})*(?:\.\d+)?)\s*(?:元|块|人民币)?",
                r"(?:每日|每天)\s*(?:预算|花费)?\s*[¥￥]?\s*([0-9]+(?:[,，][0-9]{3})*(?:\.\d+)?)\s*(?:元|块|人民币)",
            )
        )
        total_budget = capture(
            (
                r"(?:总预算|预算总共|总共预算|全部预算|整体预算)\s*(?:约|大约)?\s*[¥￥]?\s*([0-9]+(?:[,，][0-9]{3})*(?:\.\d+)?)\s*(?:元|块|人民币)?",
                r"(?:预算)\s*(?:约|大约)?\s*[¥￥]?\s*([0-9]+(?:[,，][0-9]{3})*(?:\.\d+)?)\s*(?:元|块|人民币)(?!\s*(?:每天|每日|/天))",
            )
        )
        if days is not None:
            parsed["days"] = int(days)
        if people is not None:
            parsed["people"] = int(people)
        if daily is not None:
            parsed["daily_budget"] = daily
        elif total_budget is not None:
            parsed["total_budget"] = total_budget
        return parsed

    @staticmethod
    def normalize_parameters(parameters: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(parameters)
        for key in ("days", "people"):
            try:
                value = int(normalized[key])
                if value > 0:
                    normalized[key] = value
                else:
                    normalized.pop(key, None)
            except (KeyError, TypeError, ValueError):
                normalized.pop(key, None)
        for key in ("daily_budget", "total_budget"):
            try:
                value = float(normalized[key])
                if value >= 0:
                    normalized[key] = value
                else:
                    normalized.pop(key, None)
            except (KeyError, TypeError, ValueError):
                normalized.pop(key, None)
        return normalized

    @staticmethod
    def _chinese_number(value: str) -> int:
        digits = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
        if value == "十":
            return 10
        if "十" in value:
            left, _, right = value.partition("十")
            return (digits.get(left, 1) if left else 1) * 10 + (digits.get(right, 0) if right else 0)
        if "百" in value:
            left, _, right = value.partition("百")
            return digits.get(left, 1) * 100 + BudgetEstimationAgent._chinese_number(right or "零")
        return digits.get(value, 0)
