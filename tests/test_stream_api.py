import httpx
import pytest

from backend.app import main as app_module


class FakeStreamingAgent:
    async def run(
        self,
        session_id,
        scene_code,
        message,
        parameters,
        token_sink=None,
        progress_sink=None,
    ):
        if progress_sink:
            await progress_sink("目的地：杭州。")
        if token_sink:
            await token_sink("你好，")
            await token_sink("我是旅行顾问。")
        return {
            "request_id": "request-1",
            "session_id": session_id,
            "scene_code": scene_code,
            "scene_name": "AI 行程规划",
            "answer": "你好，我是旅行顾问。",
            "result": {},
            "tools_used": [],
            "citations": [
                {
                    "type": "external_web",
                    "title": "网页正文",
                    "url": "https://example.com/private-audit-link",
                }
            ],
            "agent_name": "fake-agent",
            "reasoning_mode": "test",
            "execution_trace": [],
            "mock_mode": True,
        }


@pytest.mark.asyncio
async def test_stream_message_emits_tokens_and_final_payload(monkeypatch) -> None:
    saved: list[dict] = []

    async def fake_save(*args, **kwargs):
        saved.append({"args": args, "kwargs": kwargs})

    monkeypatch.setattr(app_module, "agent", FakeStreamingAgent())
    monkeypatch.setattr(app_module, "save_chat_exchange", fake_save)

    async def fake_session(session_id: str, user_id: str):
        return {"session_id": session_id, "messages": []}

    monkeypatch.setattr(app_module, "get_chat_session", fake_session)
    app_module.app.dependency_overrides[app_module.current_user] = lambda: {
        "id": "00000000-0000-0000-0000-000000000001",
        "username": "tester",
        "display_name": "测试用户",
        "role": "user",
        "is_active": True,
    }

    transport = httpx.ASGITransport(app=app_module.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/chat/sessions/session-1/messages/stream",
            json={"scene_code": "TRAVEL_PLAN", "message": "你好", "parameters": {}},
        )

    app_module.app.dependency_overrides.clear()

    assert response.status_code == 200
    assert "event: progress" in response.text
    assert '"message":"目的地：杭州。"' in response.text
    assert "梳理需求" not in response.text
    assert "event: token" in response.text
    assert '"token":"你好，"' in response.text
    assert "event: done" in response.text
    assert '"answer":"你好，我是旅行顾问。"' in response.text
    assert "private-audit-link" not in response.text
    assert saved[0]["args"][5]["citations"][0]["url"] == (
        "https://example.com/private-audit-link"
    )
    assert saved


@pytest.mark.asyncio
async def test_message_cannot_cross_scene_session(monkeypatch) -> None:
    async def fake_session(session_id: str, user_id: str):
        return {
            "session_id": session_id,
            "scene_code": "POI_DISCOVERY",
            "messages": [],
        }

    monkeypatch.setattr(app_module, "get_chat_session", fake_session)

    with pytest.raises(PermissionError, match="不属于当前功能"):
        await app_module.run_and_save_message(
            "poi-session",
            "user-1",
            app_module.ChatRequest(
                scene_code="TRAVEL_PLAN", message="帮我规划郑州两日游"
            ),
        )
