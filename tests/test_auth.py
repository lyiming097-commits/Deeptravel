import httpx
import pytest

from backend.app import main as app_module
from backend.app.auth import hash_password, new_token, token_digest, verify_password
from backend.app.schemas import AdminUserCreateRequest, AuthLoginRequest, AuthRegisterRequest


def test_password_hash_is_salted_and_verifiable() -> None:
    first = hash_password("correct-horse-battery-staple")
    second = hash_password("correct-horse-battery-staple")

    assert first != second
    assert verify_password("correct-horse-battery-staple", first)
    assert not verify_password("wrong-password", first)


def test_token_digest_does_not_store_raw_token() -> None:
    token = new_token()
    digest = token_digest(token)

    assert token not in digest
    assert len(digest) == 64


@pytest.mark.asyncio
async def test_chat_sessions_require_login() -> None:
    transport = httpx.ASGITransport(app=app_module.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/chat/sessions")

    assert response.status_code == 401
    assert response.json()["detail"] == "请先登录"


@pytest.mark.asyncio
async def test_regular_user_is_rejected_by_admin_dependency() -> None:
    with pytest.raises(app_module.HTTPException) as exc_info:
        await app_module.admin_user({"id": "user-1", "role": "user"})

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_session_lookup_is_scoped_to_authenticated_user(monkeypatch) -> None:
    seen: list[tuple[str, str]] = []

    async def fake_get_session(session_id: str, user_id: str):
        seen.append((session_id, user_id))

    monkeypatch.setattr(app_module, "get_chat_session", fake_get_session)
    app_module.app.dependency_overrides[app_module.current_user] = lambda: {
        "id": "user-a",
        "role": "user",
    }
    try:
        transport = httpx.ASGITransport(app=app_module.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/chat/sessions/session-owned-by-b")
    finally:
        app_module.app.dependency_overrides.clear()

    assert response.status_code == 404
    assert seen == [("session-owned-by-b", "user-a")]


@pytest.mark.asyncio
async def test_public_registration_always_creates_regular_user(monkeypatch) -> None:
    roles: list[str] = []

    async def fake_bootstrap(username: str, password: str) -> None:
        return None

    async def fake_create(username: str, password: str, role: str, display_name: str | None):
        roles.append(role)
        return {"id": "user-1", "username": username, "role": role}

    monkeypatch.setattr(app_module, "ensure_bootstrap_admin", fake_bootstrap)
    monkeypatch.setattr(app_module, "create_user", fake_create)
    request = AuthRegisterRequest(username="traveler", password="password123")

    response = await app_module.register(request)

    assert roles == ["user"]
    assert response["user"]["role"] == "user"


@pytest.mark.asyncio
async def test_admin_api_can_only_create_regular_users(monkeypatch) -> None:
    roles: list[str] = []

    async def fake_create(username: str, password: str, role: str, display_name: str | None):
        roles.append(role)
        return {"id": "user-2", "username": username, "role": role}

    monkeypatch.setattr(app_module, "create_user", fake_create)
    request = AdminUserCreateRequest(username="member", password="password123")

    response = await app_module.create_admin_user(request, {"id": "admin-1"})

    assert roles == ["user"]
    assert response["user"]["role"] == "user"


@pytest.mark.asyncio
async def test_miniapp_login_rejects_admin_account(monkeypatch) -> None:
    async def fake_bootstrap(username: str, password: str) -> None:
        return None

    async def fake_authenticate(username: str, password: str):
        return {"id": "admin-1", "username": username, "role": "admin"}

    async def unexpected_issue_token(user_id: str, ttl_days: int):
        raise AssertionError("角色校验失败后不应签发 token")

    monkeypatch.setattr(app_module, "ensure_bootstrap_admin", fake_bootstrap)
    monkeypatch.setattr(app_module, "authenticate_user", fake_authenticate)
    monkeypatch.setattr(app_module, "issue_token", unexpected_issue_token)

    with pytest.raises(app_module.HTTPException) as exc_info:
        await app_module.user_login(
            AuthLoginRequest(username="admin", password="admin123")
        )

    assert exc_info.value.status_code == 403
    assert "浏览器管理端" in exc_info.value.detail


@pytest.mark.asyncio
async def test_browser_login_rejects_regular_user(monkeypatch) -> None:
    async def fake_bootstrap(username: str, password: str) -> None:
        return None

    async def fake_authenticate(username: str, password: str):
        return {"id": "user-1", "username": username, "role": "user"}

    async def unexpected_issue_token(user_id: str, ttl_days: int):
        raise AssertionError("角色校验失败后不应签发 token")

    monkeypatch.setattr(app_module, "ensure_bootstrap_admin", fake_bootstrap)
    monkeypatch.setattr(app_module, "authenticate_user", fake_authenticate)
    monkeypatch.setattr(app_module, "issue_token", unexpected_issue_token)

    with pytest.raises(app_module.HTTPException) as exc_info:
        await app_module.admin_login(
            AuthLoginRequest(username="traveler", password="password123")
        )

    assert exc_info.value.status_code == 403
    assert "微信小程序" in exc_info.value.detail


@pytest.mark.asyncio
async def test_browser_login_accepts_admin_account(monkeypatch) -> None:
    async def fake_bootstrap(username: str, password: str) -> None:
        return None

    async def fake_authenticate(username: str, password: str):
        return {"id": "admin-1", "username": username, "role": "admin"}

    async def fake_issue_token(user_id: str, ttl_days: int):
        return "admin-token", "2099-01-01T00:00:00Z"

    monkeypatch.setattr(app_module, "ensure_bootstrap_admin", fake_bootstrap)
    monkeypatch.setattr(app_module, "authenticate_user", fake_authenticate)
    monkeypatch.setattr(app_module, "issue_token", fake_issue_token)

    response = await app_module.admin_login(
        AuthLoginRequest(username="admin", password="admin123")
    )

    assert response["access_token"] == "admin-token"
    assert response["user"]["role"] == "admin"
