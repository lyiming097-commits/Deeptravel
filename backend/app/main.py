import asyncio
import hashlib
import inspect
import ipaddress
import json
import logging
import socket
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated
from urllib.parse import urljoin, urlparse

import httpx
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.exc import SQLAlchemyError

from backend.app.agent.service import TravelAgent
from backend.app.auth import hash_password
from backend.app.auth_repository import (
    authenticate_user,
    change_password,
    create_user,
    ensure_bootstrap_admin,
    get_user_by_username,
    issue_token,
    revoke_token,
    update_user,
    user_from_token,
)
from backend.app.auth_repository import (
    list_users as list_users_repository,
)
from backend.app.config import get_settings
from backend.app.database import database_health
from backend.app.knowledge_categories import (
    build_category_tree,
    get_category,
    list_knowledge_categories,
)
from backend.app.rag.embedding import build_embedding_provider, embedding_health
from backend.app.rag.ingestion import SUPPORTED_SUFFIXES, extract_text, split_text
from backend.app.repositories import (
    complete_document_ingestion,
    create_chat_session,
    create_document,
    delete_chat_session,
    delete_document,
    fail_document_ingestion,
    find_document_by_hash,
    get_chat_session,
    get_document,
    list_all_chat_sessions,
    list_chat_sessions,
    save_chat_exchange,
    update_document_content,
)
from backend.app.repositories import (
    list_documents as list_documents_repository,
)
from backend.app.repositories import (
    publish_document as publish_document_repository,
)
from backend.app.scenes import get_scene, list_scenes
from backend.app.schemas import (
    AdminDocumentUpdateRequest,
    AdminUserCreateRequest,
    AdminUserUpdateRequest,
    AuthLoginRequest,
    AuthRegisterRequest,
    ChangePasswordRequest,
    ChatRequest,
    ChatResponse,
    WechatLoginRequest,
)

settings = get_settings()
logger = logging.getLogger(__name__)
app = FastAPI(title="DeepTravel 智能旅游助手", version="0.1.0")
agent = TravelAgent(settings)
UPLOAD_DIR = Path(__file__).resolve().parents[2] / "data" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
# Image URLs are requested by both the native ``<image>`` component and the
# real-device local-file prefetcher. Keep a small process-local cache so the
# second request is served immediately instead of downloading the same Amap
# object twice. The cache is deliberately bounded; it is only an acceleration
# layer and never changes the persisted POI data.
_IMAGE_CACHE: dict[str, tuple[float, str, bytes]] = {}
_IMAGE_CACHE_BYTES = 0
_IMAGE_CACHE_TTL_SECONDS = 3600
_IMAGE_CACHE_MAX_BYTES = 32 * 1024 * 1024
_IMAGE_CACHE_MAX_ENTRY_BYTES = 4 * 1024 * 1024
KNOWLEDGE_CATEGORIES = frozenset({
    "destination", "travel_guide", "food_lodging_transport", "travel_experience", "travel_news",
    "destination_info", "trip_plans", "food", "accommodation", "transportation",
    "practical_tips", "notices_events", "travel_updates",
})
LEGACY_CATEGORY_ALIASES = {
    # Keep old client/upload links working after the taxonomy migration.
    "guide": "trip_plans", "general": "destination_info", "未分类": "destination_info",
    "attraction": "destination_info", "city_intro": "destination_info", "culture_history": "destination_info",
    "one_day": "trip_plans", "three_day": "trip_plans", "family_trip": "trip_plans", "self_drive": "trip_plans",
    "hotel": "accommodation", "lodging_experience": "accommodation", "food": "food",
    "transportation": "transportation", "avoid_pitfalls": "practical_tips", "budget": "practical_tips",
    "faq": "practical_tips", "photography": "practical_tips",
    "opening": "notices_events", "festival": "notices_events", "traffic_update": "travel_updates", "news": "travel_updates",
}
KNOWLEDGE_CATEGORY_TERMS = {
    "destination_info": ("景点", "景区", "名胜", "古迹", "城市介绍", "城市概况", "城市简介", "文化", "历史", "古城", "人文"),
    "accommodation": ("酒店", "酒店推荐", "住宿", "民宿", "宾馆"),
    "food": ("美食", "餐厅", "餐馆", "小吃"),
    "travel_updates": ("新闻", "文旅新闻", "交通动态", "资讯", "动态"),
    "notices_events": ("开放", "开园", "闭园", "公告", "节假日", "节日", "活动"),
    "transportation": ("交通", "路线", "公交", "地铁"),
    "trip_plans": ("攻略", "游记", "行程", "一日游", "三日游", "亲子游", "自驾游"),
    "practical_tips": ("避坑", "预算", "FAQ", "常见问题", "摄影", "打卡"),
}


def infer_knowledge_category(file_name: str, requested: str | None) -> str:
    value = (requested or "").strip().lower()
    value = LEGACY_CATEGORY_ALIASES.get(value, value)
    if value in KNOWLEDGE_CATEGORIES:
        return value
    for category, terms in KNOWLEDGE_CATEGORY_TERMS.items():
        if any(term in file_name for term in terms):
            return category
    return "attraction"


def category_metadata(code: str) -> tuple[str, str]:
    """Convert a leaf/top-level code to ``category`` and ``sub_category``."""
    parents = {
        "destination_info": "destination", "trip_plans": "travel_guide",
        "food": "food_lodging_transport", "accommodation": "food_lodging_transport", "transportation": "food_lodging_transport",
        "practical_tips": "travel_experience", "notices_events": "travel_news", "travel_updates": "travel_news",
    }
    return (parents.get(code, code), code if code in parents else "")


def bearer_token(authorization: str | None) -> str:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(
            401,
            "请先登录",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return token.strip()


async def current_user(authorization: str | None = Header(default=None)) -> dict:
    user = await user_from_token(bearer_token(authorization))
    if not user:
        raise HTTPException(
            401,
            "登录已失效，请重新登录",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


async def admin_user(user: Annotated[dict, Depends(current_user)]) -> dict:
    if user["role"] != "admin":
        raise HTTPException(403, "只有管理员可以执行此操作")
    return user


CurrentUser = Annotated[dict, Depends(current_user)]
AdminUser = Annotated[dict, Depends(admin_user)]


@app.get("/health")
async def health() -> dict:
    database, embedding = await asyncio.gather(
        database_health(settings), embedding_health(settings)
    )
    services_ready = bool(database.get("connected")) and bool(embedding.get("connected"))
    if embedding.get("provider") == "ollama":
        services_ready = services_ready and bool(embedding.get("model_available"))
    return {
        "status": "ok" if services_ready else "degraded",
        "environment": settings.app_env,
        "test_mode": settings.test_mode,
        "mocks": {
            "llm": settings.llm_mocked,
            "amap": settings.amap_mocked,
            "search": settings.search_mocked,
        },
        "database": database,
        "embedding": embedding,
        "configuration": settings.configuration_status(),
    }


@app.get("/api/v1/media/amap-image")
async def amap_image(url: str) -> Response:
    """Proxy verified public images for same-origin browser loading.

    Amap/Commons remain supported, and web-search images may come from a
    public CDN whose hostname is not known ahead of time.  Validate every
    redirect and reject private/reserved DNS targets so broadening the proxy
    does not turn it into an SSRF endpoint.
    """
    global _IMAGE_CACHE_BYTES

    async def validate_public_url(candidate: str) -> None:
        parsed = urlparse(candidate.strip())
        host = (parsed.hostname or "").lower().rstrip(".")
        if parsed.scheme not in {"http", "https"} or not host or parsed.username or parsed.password:
            raise HTTPException(400, "图片地址无效")
        if host in {"localhost", "localhost.localdomain"} or host.endswith(".localhost"):
            raise HTTPException(403, "图片地址不允许访问本机")
        try:
            address = ipaddress.ip_address(host)
            if not address.is_global:
                raise HTTPException(403, "图片地址不允许访问内网")
            return
        except ValueError:
            pass
        try:
            addresses = await asyncio.to_thread(
                socket.getaddrinfo, host, parsed.port or (443 if parsed.scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            )
        except OSError as exc:
            raise HTTPException(502, "图片域名解析失败") from exc
        if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
            raise HTTPException(403, "图片地址不允许访问内网")

    current_url = url.strip()
    cache_key = current_url
    await validate_public_url(current_url)
    cached = _IMAGE_CACHE.get(cache_key)
    if cached:
        cached_at, cached_type, cached_content = cached
        if time.monotonic() - cached_at < _IMAGE_CACHE_TTL_SECONDS:
            return Response(
                content=cached_content,
                media_type=cached_type,
                headers={"Cache-Control": "public, max-age=3600"},
            )
        expired = _IMAGE_CACHE.pop(cache_key, None)
        if expired:
            _IMAGE_CACHE_BYTES -= len(expired[2])
    try:
        async with httpx.AsyncClient(follow_redirects=False, timeout=12) as client:
            for _ in range(4):
                response = await client.get(
                    current_url, headers={"User-Agent": "DeepTravel/1.0"}
                )
                if response.status_code not in {301, 302, 303, 307, 308}:
                    response.raise_for_status()
                    break
                location = response.headers.get("location")
                if not location:
                    raise HTTPException(502, "图片重定向缺少地址")
                current_url = urljoin(current_url, location)
                await validate_public_url(current_url)
            else:
                raise HTTPException(502, "图片重定向次数过多")
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(502, "图片暂时无法访问") from exc
    if len(response.content) > 8 * 1024 * 1024:
        raise HTTPException(413, "图片文件过大")
    declared_media_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    media_type = declared_media_type if declared_media_type.startswith("image/") else ""
    # Several Amap OSS objects are valid JPEG/PNG files but are labelled
    # ``application/octet-stream``. Sniff only the standard image signatures
    # so those photos remain usable without accepting arbitrary binary data.
    content = response.content
    if not media_type:
        if content.startswith(b"\xff\xd8\xff"):
            media_type = "image/jpeg"
        elif content.startswith(b"\x89PNG\r\n\x1a\n"):
            media_type = "image/png"
        elif content.startswith((b"GIF87a", b"GIF89a")):
            media_type = "image/gif"
        elif len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
            media_type = "image/webp"
    if not media_type:
        raise HTTPException(415, "远端内容不是图片")
    if len(content) <= _IMAGE_CACHE_MAX_ENTRY_BYTES:
        previous = _IMAGE_CACHE.pop(cache_key, None)
        if previous:
            _IMAGE_CACHE_BYTES -= len(previous[2])
        _IMAGE_CACHE[cache_key] = (time.monotonic(), media_type, content)
        _IMAGE_CACHE_BYTES += len(content)
        while _IMAGE_CACHE_BYTES > _IMAGE_CACHE_MAX_BYTES and _IMAGE_CACHE:
            oldest_url, oldest = next(iter(_IMAGE_CACHE.items()))
            _IMAGE_CACHE.pop(oldest_url, None)
            _IMAGE_CACHE_BYTES -= len(oldest[2])
    return Response(
        content=content,
        media_type=media_type,
        headers={"Cache-Control": "public, max-age=3600"},
    )


@app.get("/api/v1/scenes")
async def scenes() -> dict:
    return {"items": list_scenes()}


@app.get("/api/v1/knowledge/categories")
@app.get("/api/v1/admin/knowledge/categories")
async def knowledge_categories() -> dict:
    """Return the enabled category tree maintained by the database."""
    try:
        rows = await list_knowledge_categories()
    except SQLAlchemyError as exc:
        raise HTTPException(503, "知识库分类表不可用，请先执行数据库迁移") from exc
    tree = build_category_tree(rows)
    return {
        "items": [{"code": "all", "name": "全部知识", "parent_code": None,
                   "sort_order": 0, "ttl_hours": None, "children": tree}],
    }


@app.post("/api/v1/auth/register", status_code=201)
async def register(request: AuthRegisterRequest) -> dict:
    try:
        await ensure_bootstrap_admin(
            settings.admin_username, settings.admin_initial_password
        )
        user = await create_user(
            request.username,
            request.password,
            role="user",
            display_name=request.display_name,
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(409, "用户名已存在，请更换用户名") from exc
    return {"user": user}


async def _login_for_role(
    request: AuthLoginRequest,
    required_role: str | None = None,
    wrong_role_message: str = "该账号不能从当前入口登录",
) -> dict:
    try:
        await ensure_bootstrap_admin(settings.admin_username, settings.admin_initial_password)
        user = await authenticate_user(request.username, request.password)
    except SQLAlchemyError as exc:
        raise HTTPException(503, "数据库不可用，请先执行数据库初始化脚本") from exc
    if not user:
        raise HTTPException(401, "用户名或密码错误")
    if required_role and user["role"] != required_role:
        raise HTTPException(403, wrong_role_message)
    token, expires_at = await issue_token(user["id"], settings.auth_token_ttl_days)
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_at": expires_at,
        "user": user,
    }


@app.post("/api/v1/auth/login")
async def login(request: AuthLoginRequest) -> dict:
    """Backward-compatible authentication endpoint for API clients."""
    return await _login_for_role(request)


@app.post("/api/v1/auth/user/login")
async def user_login(request: AuthLoginRequest) -> dict:
    """Authenticate a regular traveler from the WeChat mini program."""
    return await _login_for_role(
        request,
        required_role="user",
        wrong_role_message="管理员账号请在浏览器管理端登录",
    )


@app.post("/api/v1/auth/admin/login")
async def admin_login(request: AuthLoginRequest) -> dict:
    """Authenticate the sole administrator from the browser console."""
    return await _login_for_role(
        request,
        required_role="admin",
        wrong_role_message="普通用户请在微信小程序登录",
    )


async def _wechat_openid(code: str) -> str:
    """Exchange a mini-program login code for a WeChat openid.

    WeChat codes are short-lived and single-use, so the exchange is performed
    for every login.  Only the openid is retained indirectly (as a deterministic
    internal username); session keys are never returned to the client or saved.
    """

    if not settings.wechat_app_id or not settings.wechat_app_secret:
        raise HTTPException(503, "微信登录尚未配置，请在后端 .env 设置 WECHAT_APP_ID 和 WECHAT_APP_SECRET")
    timeout = max(1.0, float(settings.wechat_login_timeout_seconds))
    params = {
        "appid": settings.wechat_app_id,
        "secret": settings.wechat_app_secret,
        "js_code": code,
        "grant_type": "authorization_code",
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(
                "https://api.weixin.qq.com/sns/jscode2session", params=params
            )
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("微信 jscode2session 请求失败: %s", exc)
        raise HTTPException(502, "微信登录服务暂时不可用，请稍后重试") from exc
    if not isinstance(payload, dict):
        raise HTTPException(502, "微信登录服务返回格式异常")
    error_code = payload.get("errcode")
    if error_code not in (None, 0, "0"):
        # Invalid/expired codes are client errors; provider/configuration
        # failures are reported without exposing the app secret.
        if error_code in {40029, 40163, 41008, "40029", "40163", "41008"}:
            raise HTTPException(401, "微信登录凭证无效或已过期，请重新点击微信登录")
        logger.warning("微信登录返回错误 %s: %s", error_code, payload.get("errmsg"))
        raise HTTPException(502, "微信登录服务暂时无法完成认证")
    openid = str(payload.get("openid") or "").strip()
    if not openid:
        raise HTTPException(502, "微信登录服务未返回有效用户标识")
    return openid


@app.post("/api/v1/auth/wechat/login")
async def wechat_login(request: WechatLoginRequest) -> dict:
    """Log a mini-program user in with the temporary WeChat login code.

    The database schema intentionally stays provider-agnostic: a stable hash of
    ``appid:openid`` becomes the internal username, so repeated logins resolve
    to the same regular user without storing WeChat session keys.
    """

    openid = await _wechat_openid(request.code)
    identity = hashlib.sha256(
        f"{settings.wechat_app_id}:{openid}".encode()
    ).hexdigest()[:32]
    username = f"wx_{identity}"
    # This password is only an internal credential used to reuse the existing
    # username/password repository.  It is never sent to the client.
    internal_password = f"wechat:{settings.wechat_app_secret}:{openid}"
    display_name = (request.display_name or "").strip() or "微信用户"
    try:
        await ensure_bootstrap_admin(
            settings.admin_username, settings.admin_initial_password
        )
        # Keep the legacy credential lookup for existing accounts, then fall
        # back to the identity-only lookup.  The latter is essential after a
        # user changes their password: the verified WeChat code, rather than
        # the old internal password, is the source of authentication here.
        user = await authenticate_user(username, internal_password)
        if not user:
            user = await get_user_by_username(username)
        if not user:
            try:
                user = await create_user(
                    username,
                    internal_password,
                    role="user",
                    display_name=display_name,
                )
            except SQLAlchemyError:
                # A concurrent first login may have inserted the same user.
                user = await get_user_by_username(username)
                if not user:
                    raise
        if user["role"] != "user":
            raise HTTPException(403, "管理员账号请在浏览器管理端登录")
        token, expires_at = await issue_token(
            user["id"], settings.auth_token_ttl_days
        )
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        raise HTTPException(503, "数据库不可用，请先执行数据库初始化脚本") from exc
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_at": expires_at,
        "user": user,
    }


@app.post("/api/v1/auth/logout")
async def logout(authorization: str | None = Header(default=None)) -> dict:
    await revoke_token(bearer_token(authorization))
    return {"ok": True}


@app.get("/api/v1/auth/me")
async def me(user: CurrentUser) -> dict:
    return {"user": user}


@app.patch("/api/v1/auth/me/password")
async def change_my_password(request: ChangePasswordRequest, user: CurrentUser) -> dict:
    """Change the password belonging to the currently authenticated user."""

    if str(user.get("username") or "").lower().startswith("wx_"):
        raise HTTPException(400, "微信登录无法修改密码")
    if request.current_password == request.new_password:
        raise HTTPException(400, "新密码不能与当前密码相同")
    try:
        changed = await change_password(
            user["id"], request.current_password, request.new_password
        )
    except SQLAlchemyError as exc:
        raise HTTPException(503, "数据库不可用，请稍后重试") from exc
    if not changed:
        raise HTTPException(400, "当前密码不正确")
    return {"ok": True, "message": "密码修改成功"}


@app.get("/api/v1/admin/users")
async def list_users(_: AdminUser) -> dict:
    try:
        return {"items": await list_users_repository()}
    except SQLAlchemyError as exc:
        raise HTTPException(503, "数据库不可用") from exc


@app.post("/api/v1/admin/users", status_code=201)
async def create_admin_user(
    request: AdminUserCreateRequest, _: AdminUser
) -> dict:
    try:
        user = await create_user(
            request.username,
            request.password,
            role="user",
            display_name=request.display_name,
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(409, "用户名已存在，请更换用户名") from exc
    return {"user": user}


@app.patch("/api/v1/admin/users/{user_id}")
async def update_admin_user(
    user_id: str,
    request: AdminUserUpdateRequest,
    current: AdminUser,
) -> dict:
    if user_id == current["id"] and request.is_active is False:
        raise HTTPException(400, "不能停用当前管理员账号")
    fields = request.model_dump(exclude_none=True)
    if "password" in fields:
        fields["password_hash"] = hash_password(fields.pop("password"))
    try:
        user = await update_user(user_id, fields)
    except SQLAlchemyError as exc:
        raise HTTPException(400, "用户不存在或更新失败") from exc
    if not user:
        raise HTTPException(404, "用户不存在")
    return {"user": user}


@app.post("/api/v1/chat/sessions", status_code=201)
async def create_session(user: CurrentUser, scene_code: str = "TRAVEL_PLAN") -> dict:
    try:
        return await create_chat_session(
            user["id"], get_scene(scene_code).code, settings.max_chat_sessions_per_scene
        )
    except SQLAlchemyError as exc:
        raise HTTPException(503, "数据库不可用，请检查 DATABASE_URL") from exc


@app.get("/api/v1/chat/sessions")
async def sessions(user: CurrentUser, scene_code: str = "TRAVEL_PLAN") -> dict:
    try:
        return {
            "items": await list_chat_sessions(user["id"], get_scene(scene_code).code)
        }
    except SQLAlchemyError as exc:
        raise HTTPException(503, "数据库不可用") from exc


@app.get("/api/v1/chat/sessions/all")
async def all_sessions(user: CurrentUser) -> dict:
    """Return the user's recent sessions grouped across all chat scenes."""

    try:
        items = await list_all_chat_sessions(
            user["id"], settings.max_chat_sessions_per_scene
        )
    except SQLAlchemyError as exc:
        raise HTTPException(503, "数据库不可用") from exc
    return {
        "items": [
            {
                **item,
                "scene_name": get_scene(item["scene_code"]).name,
            }
            for item in items
        ]
    }


@app.delete("/api/v1/chat/sessions/{session_id}")
async def delete_session(session_id: str, user: CurrentUser) -> dict:
    try:
        deleted = await delete_chat_session(session_id, user["id"])
    except (SQLAlchemyError, ValueError) as exc:
        raise HTTPException(503, "数据库不可用或会话 ID 不合法") from exc
    if not deleted:
        raise HTTPException(404, "会话不存在或无权删除")
    return {"deleted": True, "session_id": session_id}


@app.post("/api/v1/chat/sessions/{session_id}/messages", response_model=ChatResponse)
async def send_message(
    session_id: str, request: ChatRequest, user: CurrentUser
) -> dict:
    try:
        return await run_and_save_message(session_id, user["id"], request)
    except SQLAlchemyError as exc:
        raise HTTPException(503, "数据库不可用，请检查 DATABASE_URL 和表结构") from exc
    except PermissionError as exc:
        raise HTTPException(404, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from exc


async def run_and_save_message(
    session_id: str,
    user_id: str,
    request: ChatRequest,
    token_sink: Callable[[str], Awaitable[None]] | None = None,
    progress_sink: Callable[[str], Awaitable[None]] | None = None,
) -> dict:
    chat_session = await get_chat_session(session_id, user_id)
    if not chat_session:
        raise PermissionError("会话不存在或无权访问")
    if chat_session.get("scene_code", get_scene(request.scene_code).code) != get_scene(
        request.scene_code
    ).code:
        raise PermissionError("该会话不属于当前功能，请在对应功能的会话框中继续")
    effective_parameters = dict(request.parameters)
    effective_parameters["_conversation_history"] = [
        {"role": item["role"], "content": item["content"]}
        for item in chat_session.get("messages", [])[
            -max(1, settings.short_memory_messages) :
        ]
        if item.get("role") in {"user", "assistant"}
    ]
    run_kwargs = {"token_sink": token_sink}
    if progress_sink is not None:
        try:
            run_parameters = inspect.signature(agent.run).parameters
        except (TypeError, ValueError):
            run_parameters = {}
        if "progress_sink" in run_parameters or any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in run_parameters.values()
        ):
            run_kwargs["progress_sink"] = progress_sink
    response = await agent.run(
        session_id,
        request.scene_code,
        request.message,
        effective_parameters,
        **run_kwargs,
    )
    await save_chat_exchange(
        session_id,
        response["request_id"],
        user_id,
        request.message,
        response["answer"],
        {
            "scene_code": response["scene_code"],
            "tools_used": response["tools_used"],
            "citations": response["citations"],
            "result": response["result"],
            "agent_name": response["agent_name"],
            "reasoning_mode": response["reasoning_mode"],
            "execution_trace": response["execution_trace"],
        },
    )
    # Keep full external citations in the server-side audit record, but do not
    # return public-search URLs to the chat client. The user should receive the
    # extracted page content synthesized by the model, not a list of links.
    public_response = dict(response)
    public_response["citations"] = public_citations(response.get("citations", []))
    return public_response


def public_citations(citations: list[dict]) -> list[dict]:
    """Remove public-search URLs while retaining non-link audit labels."""

    return [
        {
            key: value
            for key, value in citation.items()
            if not (citation.get("type") == "external_web" and key == "url")
        }
        for citation in citations
    ]


def public_chat_session(chat_session: dict) -> dict:
    """Return saved messages without exposing archived public-search URLs."""

    result = dict(chat_session)
    result["messages"] = []
    for message in chat_session.get("messages", []):
        public_message = dict(message)
        metadata = dict(public_message.get("metadata") or {})
        metadata["citations"] = public_citations(metadata.get("citations", []))
        public_message["metadata"] = metadata
        result["messages"].append(public_message)
    return result


def sse_event(event: str, payload: dict) -> str:
    data = json.dumps(payload, ensure_ascii=False, default=str, separators=(",", ":"))
    return f"event: {event}\ndata: {data}\n\n"


@app.post("/api/v1/chat/sessions/{session_id}/messages/stream")
async def stream_message(
    session_id: str,
    request: ChatRequest,
    user: CurrentUser,
) -> StreamingResponse:
    """Run tools asynchronously and stream safe progress plus the grounded answer."""
    queue: asyncio.Queue[tuple[str, dict]] = asyncio.Queue()

    async def emit_token(token: str) -> None:
        await queue.put(("token", {"token": token}))

    async def emit_progress(message: str) -> None:
        await queue.put(("progress", {"message": message}))

    async def produce() -> None:
        try:
            response = await run_and_save_message(
                session_id,
                user["id"],
                request,
                emit_token,
                emit_progress,
            )
            await queue.put(("done", response))
        except SQLAlchemyError as exc:
            logger.exception("流式对话写入数据库失败: %s", exc.__class__.__name__)
            await queue.put(
                ("error", {"detail": "数据库不可用，请检查 DATABASE_URL 和表结构"})
            )
        except RuntimeError as exc:
            await queue.put(("error", {"detail": str(exc)}))
        except PermissionError as exc:
            await queue.put(("error", {"detail": str(exc)}))
        except Exception:  # noqa: BLE001 - stream errors must become a terminal SSE event
            await queue.put(("error", {"detail": "流式对话处理失败"}))
        finally:
            await queue.put(("close", {}))

    producer = asyncio.create_task(produce())

    async def events() -> AsyncIterator[str]:
        try:
            while True:
                event, payload = await queue.get()
                if event == "close":
                    break
                yield sse_event(event, payload)
        finally:
            if not producer.done():
                producer.cancel()
                with suppress(asyncio.CancelledError):
                    await producer

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/v1/chat/sessions/{session_id}")
async def get_session(session_id: str, user: CurrentUser) -> dict:
    try:
        chat_session = await get_chat_session(session_id, user["id"])
    except (SQLAlchemyError, ValueError) as exc:
        raise HTTPException(503, "数据库不可用或会话 ID 不合法") from exc
    if not chat_session:
        raise HTTPException(404, "会话不存在")
    return public_chat_session(chat_session)


@app.post("/api/v1/admin/knowledge/documents", status_code=201)
async def upload_document(
    file: Annotated[UploadFile, File()],
    _: AdminUser,
    source_url: Annotated[str | None, Form()] = None,
    category: Annotated[str | None, Form()] = None,
    sub_category: Annotated[str | None, Form()] = None,
    city: Annotated[str | None, Form()] = None,
    province: Annotated[str | None, Form()] = None,
    season: Annotated[str | None, Form()] = None,
    travel_type: Annotated[str | None, Form()] = None,
) -> dict:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise HTTPException(400, "仅支持 PDF、DOCX、Markdown、TXT、HTML 和 CSV")
    requested_category = sub_category or category
    normalized_category = infer_knowledge_category(file.filename or "", requested_category)
    try:
        category_row = await get_category(normalized_category)
    except SQLAlchemyError as exc:
        raise HTTPException(503, "知识库分类表不可用，请先执行数据库迁移") from exc
    if not category_row:
        raise HTTPException(400, "知识库分类无效，请从分类树中选择")
    parent_category, inferred_sub_category = category_metadata(normalized_category)
    if category_row.get("parent_code"):
        parent_category = str(category_row["parent_code"])
        inferred_sub_category = normalized_category
    elif normalized_category in KNOWLEDGE_CATEGORIES:
        inferred_sub_category = ""
    content = await file.read(settings.max_upload_bytes + 1)
    if not content:
        raise HTTPException(400, "文件内容为空")
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(413, "文件超过允许的大小限制")
    file_hash = hashlib.sha256(content).hexdigest()
    try:
        duplicate = await find_document_by_hash(file_hash)
        if duplicate:
            raise HTTPException(409, detail={"message": "文档已存在", "document": duplicate})
        document_id = hashlib.sha256(f"{file_hash}:{file.filename}".encode()).hexdigest()[:32]
        target = UPLOAD_DIR / f"{document_id}{suffix}"
        target.write_bytes(content)
        expires_at = None
        if category_row.get("ttl_hours"):
            expires_at = datetime.now(UTC) + timedelta(hours=int(category_row["ttl_hours"]))
        document = await create_document(
            file.filename or target.name,
            file_hash,
            file.content_type,
            target,
            source_url,
            expires_at=expires_at,
        )
        try:
            text = extract_text(target)
            chunks = split_text(text)
            if not chunks:
                raise ValueError("文档未提取到可用文本")
            for chunk in chunks:
                chunk["metadata"] = {
                    "file_name": file.filename,
                    "source_url": source_url,
                    "category": parent_category,
                    "sub_category": inferred_sub_category,
                    "city": (city or "").strip(),
                    "province": (province or "").strip(),
                    "season": (season or "").strip(),
                    "travel_type": (travel_type or "").strip(),
                    "source": source_url or "administrator_upload",
                    "update_time": datetime.now(UTC).isoformat(),
                }
            embedding = build_embedding_provider(settings)
            vectors = await embedding.embed_documents([chunk["content"] for chunk in chunks])
            await complete_document_ingestion(str(document["id"]), chunks, vectors)
            document.update({"status": "REVIEWING", "chunk_count": len(chunks)})
            return document
        except Exception as exc:
            await fail_document_ingestion(str(document["id"]), str(exc))
            raise HTTPException(422, f"文档处理失败：{exc}") from exc
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        raise HTTPException(503, "数据库不可用或尚未初始化新表结构") from exc


@app.get("/api/v1/admin/knowledge/documents")
async def list_documents(_: AdminUser) -> dict:
    try:
        return {"items": await list_documents_repository()}
    except SQLAlchemyError as exc:
        raise HTTPException(503, "数据库不可用") from exc


@app.get("/api/v1/admin/knowledge/documents/{document_id}")
async def get_knowledge_document(document_id: str, _: AdminUser) -> dict:
    try:
        document = await get_document(document_id)
    except (SQLAlchemyError, ValueError) as exc:
        raise HTTPException(503, "数据库不可用或文档 ID 不合法") from exc
    if not document:
        raise HTTPException(404, "文档不存在")
    return document


@app.patch("/api/v1/admin/knowledge/documents/{document_id}")
async def update_knowledge_document(
    document_id: str, request: AdminDocumentUpdateRequest, _: AdminUser
) -> dict:
    try:
        embedding = agent.tools.rag.retriever.embedding
        vector = await embedding.embed_query(request.content)
        document = await update_document_content(document_id, request.content, vector)
    except (SQLAlchemyError, ValueError, RuntimeError) as exc:
        raise HTTPException(422, f"文档更新失败：{exc}") from exc
    if not document:
        raise HTTPException(404, "文档不存在")
    return document


@app.delete("/api/v1/admin/knowledge/documents/{document_id}")
async def delete_knowledge_document(document_id: str, _: AdminUser) -> dict:
    try:
        deleted = await delete_document(document_id)
    except (SQLAlchemyError, ValueError) as exc:
        raise HTTPException(503, "数据库不可用或文档 ID 不合法") from exc
    if not deleted:
        raise HTTPException(404, "文档不存在")
    return {"deleted": True, "document_id": document_id}


@app.post("/api/v1/admin/knowledge/documents/{document_id}/publish")
async def publish_knowledge_document(
    document_id: str, _: AdminUser
) -> dict:
    try:
        document = await publish_document_repository(document_id)
    except (SQLAlchemyError, ValueError) as exc:
        raise HTTPException(503, "数据库不可用或文档 ID 不合法") from exc
    if not document:
        raise HTTPException(409, "只有 REVIEWING 状态的文档可以发布")
    return document
