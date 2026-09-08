"""Database-backed knowledge category helpers.

The API is the single source of truth for the UI.  Keeping the seed data in a
small module also gives ingestion a safe fallback while a fresh database is
being migrated.
"""

from typing import Any

from sqlalchemy import text

from backend.app.database import session_scope

# Keep the fallback seed in sync with the compact taxonomy migration.  The
# database remains the source of truth; this list is only useful while a new
# database is being bootstrapped or when a deployment has not run Alembic yet.
SEED_CATEGORIES: tuple[dict[str, Any], ...] = (
    {"code": "destination", "name": "目的地", "parent_code": None, "sort_order": 10},
    {"code": "travel_guide", "name": "旅游攻略", "parent_code": None, "sort_order": 20},
    {"code": "food_lodging_transport", "name": "吃住行", "parent_code": None, "sort_order": 30},
    {"code": "travel_experience", "name": "旅游经验", "parent_code": None, "sort_order": 40},
    {"code": "travel_news", "name": "旅游资讯", "parent_code": None, "sort_order": 50},
    {"code": "destination_info", "name": "景点与城市", "parent_code": "destination", "sort_order": 10},
    {"code": "trip_plans", "name": "行程攻略", "parent_code": "travel_guide", "sort_order": 10},
    {"code": "food", "name": "美食", "parent_code": "food_lodging_transport", "sort_order": 10},
    {"code": "accommodation", "name": "住宿", "parent_code": "food_lodging_transport", "sort_order": 20},
    {"code": "transportation", "name": "交通", "parent_code": "food_lodging_transport", "sort_order": 30},
    {"code": "practical_tips", "name": "实用经验", "parent_code": "travel_experience", "sort_order": 10},
    {"code": "notices_events", "name": "景区与活动", "parent_code": "travel_news", "sort_order": 10, "ttl_hours": 168},
    {"code": "travel_updates", "name": "旅游动态", "parent_code": "travel_news", "sort_order": 20, "ttl_hours": 336},
)


async def list_knowledge_categories() -> list[dict[str, Any]]:
    async with session_scope() as session:
        rows = (
            await session.execute(
                text(
                    """SELECT code, name, parent_code, sort_order, enabled, ttl_hours
                       FROM knowledge_category
                       WHERE enabled = true
                       ORDER BY sort_order, name"""
                )
            )
        ).mappings().all()
    return [dict(row) for row in rows]


def build_category_tree(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    nodes = {
        row["code"]: {
            "code": row["code"],
            "name": row["name"],
            "parent_code": row.get("parent_code"),
            "sort_order": row.get("sort_order", 0),
            "ttl_hours": row.get("ttl_hours"),
            "children": [],
        }
        for row in rows
    }
    roots: list[dict[str, Any]] = []
    for node in nodes.values():
        parent = nodes.get(node["parent_code"])
        if parent:
            parent["children"].append(node)
        else:
            roots.append(node)
    for node in nodes.values():
        node["children"].sort(key=lambda item: (item["sort_order"], item["name"]))
    roots.sort(key=lambda item: (item["sort_order"], item["name"]))
    return roots


async def get_category(code: str) -> dict[str, Any] | None:
    async with session_scope() as session:
        row = (
            await session.execute(
                text(
                    """SELECT code, name, parent_code, sort_order, enabled, ttl_hours
                       FROM knowledge_category WHERE code = :code AND enabled = true"""
                ),
                {"code": code},
            )
        ).mappings().first()
    return dict(row) if row else None
