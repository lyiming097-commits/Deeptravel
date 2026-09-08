from enum import StrEnum


class Role(StrEnum):
    USER = "USER"
    KNOWLEDGE_ADMIN = "KNOWLEDGE_ADMIN"
    CONTENT_REVIEWER = "CONTENT_REVIEWER"
    SYSTEM_ADMIN = "SYSTEM_ADMIN"


def require_role(role: Role, allowed: set[Role]) -> None:
    if role not in allowed:
        raise PermissionError(f"角色 {role} 无权执行此操作")
