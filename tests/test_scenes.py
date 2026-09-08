from backend.app.agent.service import TravelAgent
from backend.app.config import Settings
from backend.app.maps import MockMapProvider
from backend.app.scenes import SCENES, get_scene, list_scenes


def test_all_frontend_scenes_are_exposed() -> None:
    codes = {item["code"] for item in list_scenes()}
    assert codes == {
        "TRAVEL_PLAN",
        "POI_DISCOVERY",
        "ROUTE_PLANNING",
        "BUDGET_ESTIMATION",
    }


def test_scene_welcome_messages_are_user_facing_and_hide_internal_workflow() -> None:
    forbidden = ("知识库", "MCP", "Reflection", "联网搜索", "工具调用")

    for scene in SCENES.values():
        assert scene.welcome_message
        assert not any(term in scene.welcome_message for term in forbidden)


def test_unknown_scene_falls_back_to_travel_plan() -> None:
    assert get_scene("unknown").code == "TRAVEL_PLAN"


def test_scene_tools_match_specialist_agent_whitelists() -> None:
    service = TravelAgent(
        Settings(_env_file=None, mock_llm=True, mock_amap=True, mock_search=True)
    )

    for code, scene in SCENES.items():
        assert set(scene.allowed_tools) == set(service.agents[code].allowed_tools)


def test_service_honours_map_mock_switch() -> None:
    service = TravelAgent(
        Settings(_env_file=None, mock_llm=True, mock_amap=True, mock_search=True)
    )

    assert isinstance(service.tools.amap.provider, MockMapProvider)


def test_visual_tools_are_constructed_once_and_injected_into_agents() -> None:
    service = TravelAgent(
        Settings(_env_file=None, mock_llm=True, mock_amap=True, mock_search=True)
    )

    assert service.agents["TRAVEL_PLAN"].media_tool is service.tools.poi_media
    assert service.agents["TRAVEL_PLAN"].map_tool is service.tools.itinerary_map
    assert service.agents["ROUTE_PLANNING"].map_tool is service.tools.itinerary_map
