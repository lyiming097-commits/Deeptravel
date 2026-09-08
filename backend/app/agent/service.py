import asyncio
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import uuid4

from backend.app.agent.base import short_term_memory, stream_answer_tokens, stream_progress
from backend.app.agent.budget_agent import BudgetEstimationAgent
from backend.app.agent.poi_agent import PoiDiscoveryAgent
from backend.app.agent.route_agent import RoutePlanningAgent
from backend.app.agent.travel_plan_agent import TravelPlanningAgent
from backend.app.config import Settings
from backend.app.llm.deepseek import DeepSeekClient
from backend.app.scenes import get_scene
from backend.app.tools import AgentToolRegistry


class TravelAgent:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.llm = DeepSeekClient(
            settings.deepseek_api_key,
            settings.deepseek_base_url,
            settings.deepseek_chat_model,
            settings.deepseek_timeout_seconds,
            settings.deepseek_max_retries,
        )
        self.tools = AgentToolRegistry.from_settings(settings)
        shared = {"settings": settings, "llm": self.llm}
        self.agents = {
            "TRAVEL_PLAN": TravelPlanningAgent(
                **shared,
                rag_tool=self.tools.rag,
                web_tool=self.tools.web,
                amap_tool=self.tools.amap,
                media_tool=self.tools.poi_media,
                map_tool=self.tools.itinerary_map,
            ),
            "POI_DISCOVERY": PoiDiscoveryAgent(
                **shared,
                rag_tool=self.tools.rag,
                web_tool=self.tools.web,
                amap_tool=self.tools.amap,
                media_tool=self.tools.poi_media,
            ),
            "ROUTE_PLANNING": RoutePlanningAgent(
                **shared,
                amap_tool=self.tools.amap,
                web_tool=self.tools.web,
                railway_tool=self.tools.railway,
                map_tool=self.tools.itinerary_map,
            ),
            "BUDGET_ESTIMATION": BudgetEstimationAgent(
                **shared, web_tool=self.tools.web
            ),
        }

    async def run(
        self,
        session_id: str,
        scene_code: str,
        message: str,
        parameters: dict[str, Any],
        token_sink: Callable[[str], Awaitable[None]] | None = None,
        progress_sink: Callable[[str], Awaitable[None]] | None = None,
    ) -> dict[str, Any]:
        scene = get_scene(scene_code)
        specialist = self.agents[scene.code]
        try:
            memory = parameters.get("_conversation_history", [])
            with (
                stream_answer_tokens(token_sink),
                stream_progress(progress_sink),
                short_term_memory(memory),
            ):
                async with asyncio.timeout(self.settings.agent_timeout_seconds):
                    outcome = await specialist.run(message, parameters)
        except TimeoutError as exc:
            raise RuntimeError("专项 Agent 执行超时") from exc

        return {
            "request_id": str(uuid4()),
            "session_id": session_id,
            "scene_code": scene.code,
            "scene_name": scene.name,
            "answer": outcome.answer,
            "result": outcome.result,
            "tools_used": outcome.tools_used,
            "citations": outcome.citations,
            "agent_name": outcome.agent_name,
            "reasoning_mode": outcome.reasoning_mode,
            "execution_trace": outcome.execution_trace,
            "mock_mode": self.settings.any_mocked,
        }
