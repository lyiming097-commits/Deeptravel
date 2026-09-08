from typing import Any

from pydantic import BaseModel, Field


class AuthCredentials(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_\-一-鿿]+$")
    password: str = Field(min_length=8, max_length=128)


class AuthRegisterRequest(AuthCredentials):
    display_name: str | None = Field(default=None, max_length=80)


class AuthLoginRequest(AuthCredentials):
    pass


class ChangePasswordRequest(BaseModel):
    """Credentials used by an authenticated user to change their password."""

    current_password: str = Field(min_length=8, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class WechatLoginRequest(BaseModel):
    """Code returned by ``uni.login({ provider: 'weixin' })``."""

    code: str = Field(min_length=1, max_length=512)
    display_name: str | None = Field(default=None, max_length=80)


class AdminUserCreateRequest(AuthCredentials):
    display_name: str | None = Field(default=None, max_length=80)


class AdminUserUpdateRequest(BaseModel):
    display_name: str | None = Field(default=None, max_length=80)
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=128)


class ChatRequest(BaseModel):
    scene_code: str = "TRAVEL_PLAN"
    message: str = Field(min_length=1, max_length=4000)
    parameters: dict[str, Any] = Field(default_factory=dict)


class ChatResponse(BaseModel):
    request_id: str
    session_id: str
    scene_code: str
    scene_name: str
    answer: str
    result: dict[str, Any] | None = None
    tools_used: list[str] = Field(default_factory=list)
    citations: list[dict[str, Any]] = Field(default_factory=list)
    agent_name: str
    reasoning_mode: str
    execution_trace: list[dict[str, Any]] = Field(default_factory=list)
    mock_mode: bool = False


class AdminDocumentUpdateRequest(BaseModel):
    content: str = Field(min_length=1, max_length=200_000)
