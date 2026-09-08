from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import text

from backend.app.auth import hash_password, new_token, token_digest, verify_password
from backend.app.database import session_scope


def normalize_username(username: str) -> str:
    return username.strip().lower()


def public_user(row: Any) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "username": row["username"],
        "display_name": row["display_name"] or row["username"],
        "role": row["role"],
        "is_active": bool(row["is_active"]),
        "created_at": row["created_at"],
        "updated_at": row.get("updated_at") if hasattr(row, "get") else None,
    }


async def ensure_bootstrap_admin(username: str, password: str) -> None:
    username = normalize_username(username)
    if not username or not password:
        return
    async with session_scope() as session:
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext('deeptravel-bootstrap-admin'))")
        )
        await session.execute(
            text(
                """
                INSERT INTO app_user (id, username, display_name, password_hash, role)
                SELECT :id, :username, :display_name, :password_hash, 'admin'
                WHERE NOT EXISTS (SELECT 1 FROM app_user WHERE role = 'admin')
                ON CONFLICT (username) DO NOTHING
                """
            ),
            {
                "id": uuid4(),
                "username": username,
                "display_name": username,
                "password_hash": hash_password(password),
            },
        )


async def create_user(
    username: str,
    password: str,
    role: str = "user",
    display_name: str | None = None,
) -> dict[str, Any]:
    normalized = normalize_username(username)
    user_id = uuid4()
    async with session_scope() as session:
        if role == "admin":
            await session.execute(
                text("SELECT pg_advisory_xact_lock(hashtext('deeptravel-bootstrap-admin'))")
            )
            has_admin = await session.scalar(
                text("SELECT EXISTS (SELECT 1 FROM app_user WHERE role = 'admin')")
            )
            if has_admin:
                raise ValueError("系统只允许一个管理员账号")
        row = (
            (
                await session.execute(
                    text(
                        """
                        INSERT INTO app_user
                          (id, username, display_name, password_hash, role)
                        VALUES (:id, :username, :display_name, :password_hash, :role)
                        RETURNING id, username, display_name, role, is_active,
                                  created_at, updated_at
                        """
                    ),
                    {
                        "id": user_id,
                        "username": normalized,
                        "display_name": display_name or normalized,
                        "password_hash": hash_password(password),
                        "role": role,
                    },
                )
            )
            .mappings()
            .one()
        )
    return public_user(row)


async def authenticate_user(username: str, password: str) -> dict[str, Any] | None:
    async with session_scope() as session:
        row = (
            (
                await session.execute(
                    text(
                        """
                        SELECT id, username, display_name, password_hash, role,
                               is_active, created_at, updated_at
                        FROM app_user WHERE username = :username
                        """
                    ),
                    {"username": normalize_username(username)},
                )
            )
            .mappings()
            .first()
        )
    if not row or not row["is_active"] or not verify_password(password, row["password_hash"]):
        return None
    return public_user(row)


async def get_user_by_username(username: str) -> dict[str, Any] | None:
    """Look up an active user after an external identity was authenticated."""

    async with session_scope() as session:
        row = (
            (
                await session.execute(
                    text(
                        """
                        SELECT id, username, display_name, role, is_active,
                               created_at, updated_at
                        FROM app_user WHERE username = :username
                        """
                    ),
                    {"username": normalize_username(username)},
                )
            )
            .mappings()
            .first()
        )
    if not row or not row["is_active"]:
        return None
    return public_user(row)


async def change_password(
    user_id: str, current_password: str, new_password: str
) -> bool:
    """Verify and replace one user's password.

    Returning ``False`` for a missing/inactive account or an incorrect current
    password lets the API expose one safe error without leaking account
    existence.  The authenticated bearer token remains valid, so a user is
    not unexpectedly logged out on the device where the change was made.
    """

    async with session_scope() as session:
        row = (
            (
                await session.execute(
                    text(
                        "SELECT username, password_hash, is_active FROM app_user "
                        "WHERE id = CAST(:id AS uuid)"
                    ),
                    {"id": user_id},
                )
            )
            .mappings()
            .first()
        )
        if not row or not row["is_active"] or not verify_password(
            current_password, row["password_hash"]
        ):
            return False
        await session.execute(
            text(
                "UPDATE app_user SET password_hash = :password_hash, "
                "updated_at = :updated_at WHERE id = CAST(:id AS uuid)"
            ),
            {
                "id": user_id,
                "password_hash": hash_password(new_password),
                "updated_at": datetime.now(UTC),
            },
        )
    return True


async def issue_token(user_id: str, ttl_days: int) -> tuple[str, datetime]:
    token = new_token()
    expires_at = datetime.now(UTC) + timedelta(days=max(1, ttl_days))
    async with session_scope() as session:
        await session.execute(
            text(
                """
                INSERT INTO auth_session (token_hash, user_id, expires_at)
                VALUES (:token_hash, CAST(:user_id AS uuid), :expires_at)
                """
            ),
            {
                "token_hash": token_digest(token),
                "user_id": user_id,
                "expires_at": expires_at,
            },
        )
    return token, expires_at


async def user_from_token(token: str) -> dict[str, Any] | None:
    if not token:
        return None
    async with session_scope() as session:
        row = (
            (
                await session.execute(
                    text(
                        """
                        SELECT u.id, u.username, u.display_name, u.role, u.is_active,
                               u.created_at, u.updated_at
                        FROM auth_session a
                        JOIN app_user u ON u.id = a.user_id
                        WHERE a.token_hash = :token_hash
                          AND a.expires_at > now()
                          AND u.is_active = true
                        """
                    ),
                    {"token_hash": token_digest(token)},
                )
            )
            .mappings()
            .first()
        )
        if row:
            await session.execute(
                text(
                    "UPDATE auth_session SET last_seen_at = now() WHERE token_hash = :token_hash"
                ),
                {"token_hash": token_digest(token)},
            )
    return public_user(row) if row else None


async def revoke_token(token: str) -> None:
    async with session_scope() as session:
        await session.execute(
            text("DELETE FROM auth_session WHERE token_hash = :token_hash"),
            {"token_hash": token_digest(token)},
        )


async def list_users() -> list[dict[str, Any]]:
    async with session_scope() as session:
        rows = (
            (
                await session.execute(
                    text(
                        """
                        SELECT id, username, display_name, role, is_active,
                               created_at, updated_at
                        FROM app_user ORDER BY created_at DESC
                        """
                    )
                )
            )
            .mappings()
            .all()
        )
    return [public_user(row) for row in rows]


async def update_user(user_id: str, fields: dict[str, Any]) -> dict[str, Any] | None:
    allowed = {"display_name", "is_active", "password_hash"}
    updates = {key: value for key, value in fields.items() if key in allowed}
    if not updates:
        return await get_user(user_id)
    updates["updated_at"] = datetime.now(UTC)
    assignments = ", ".join(f"{key} = :{key}" for key in updates)
    async with session_scope() as session:
        row = (
            (
                await session.execute(
                    text(
                        f"""
                        UPDATE app_user SET {assignments}
                        WHERE id = CAST(:id AS uuid)
                        RETURNING id, username, display_name, role, is_active,
                                  created_at, updated_at
                        """
                    ),
                    {**updates, "id": user_id},
                )
            )
            .mappings()
            .first()
        )
    return public_user(row) if row else None


async def get_user(user_id: str) -> dict[str, Any] | None:
    async with session_scope() as session:
        row = (
            (
                await session.execute(
                    text(
                        """
                        SELECT id, username, display_name, role, is_active,
                               created_at, updated_at
                        FROM app_user WHERE id = CAST(:id AS uuid)
                        """
                    ),
                    {"id": user_id},
                )
            )
            .mappings()
            .first()
        )
    return public_user(row) if row else None


async def purge_expired_tokens() -> int:
    async with session_scope() as session:
        result = await session.execute(text("DELETE FROM auth_session WHERE expires_at <= now()"))
    return result.rowcount or 0
