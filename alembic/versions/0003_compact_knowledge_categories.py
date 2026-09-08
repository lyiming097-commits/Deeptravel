"""Merge the knowledge taxonomy into a small, maintainable tree.

The previous migration created many narrowly-scoped leaf categories.  This
migration keeps the five business groups and merges leaves which have the same
retrieval intent.  Existing chunks are re-tagged before the old rows are
removed, so published documents remain searchable without manual re-upload.
"""

import sqlalchemy as sa

from alembic import op

revision = "0003_compact_categories"
down_revision = "0002_knowledge_categories"
branch_labels = None
depends_on = None


_ROWS = (
    ("destination_info", "景点与城市", "destination", 10, None),
    ("trip_plans", "行程攻略", "travel_guide", 10, None),
    ("food", "美食", "food_lodging_transport", 10, None),
    ("accommodation", "住宿", "food_lodging_transport", 20, None),
    ("transportation", "交通", "food_lodging_transport", 30, None),
    ("practical_tips", "实用经验", "travel_experience", 10, None),
    ("notices_events", "景区与活动", "travel_news", 10, 168),
    ("travel_updates", "旅游动态", "travel_news", 20, 336),
)

# Old leaf (and parent) codes -> compact parent/leaf metadata.
_MAPPING = {
    "attraction": ("destination", "destination_info"),
    "city_intro": ("destination", "destination_info"),
    "culture_history": ("destination", "destination_info"),
    "one_day": ("travel_guide", "trip_plans"),
    "three_day": ("travel_guide", "trip_plans"),
    "family_trip": ("travel_guide", "trip_plans"),
    "self_drive": ("travel_guide", "trip_plans"),
    "food": ("food_lodging_transport", "food"),
    "hotel": ("food_lodging_transport", "accommodation"),
    "lodging_experience": ("food_lodging_transport", "accommodation"),
    "transportation": ("food_lodging_transport", "transportation"),
    "avoid_pitfalls": ("travel_experience", "practical_tips"),
    "budget": ("travel_experience", "practical_tips"),
    "faq": ("travel_experience", "practical_tips"),
    "photography": ("travel_experience", "practical_tips"),
    "opening": ("travel_news", "notices_events"),
    "festival": ("travel_news", "notices_events"),
    "traffic_update": ("travel_news", "travel_updates"),
    "news": ("travel_news", "travel_updates"),
}

_ROOT_DEFAULTS = {
    "destination": "destination_info",
    "travel_guide": "trip_plans",
    "food_lodging_transport": "food",
    "travel_experience": "practical_tips",
    "travel_news": "travel_updates",
}

_OBSOLETE_CODES = (
    "attraction", "city_intro", "culture_history", "one_day", "three_day",
    "family_trip", "self_drive", "hotel", "lodging_experience", "avoid_pitfalls",
    "budget", "faq", "photography", "opening", "festival", "traffic_update", "news",
)


def upgrade() -> None:
    # Insert compact leaves first.  ``ON CONFLICT`` makes the migration safe
    # for databases where an operator already created one of the rows.
    for code, name, parent, order, ttl in _ROWS:
        op.execute(
            sa.text(
                """INSERT INTO knowledge_category
                   (code, name, parent_code, sort_order, ttl_hours)
                   VALUES (:code, :name, :parent, :sort_order, :ttl)
                   ON CONFLICT (code) DO UPDATE SET
                     name = EXCLUDED.name,
                     parent_code = EXCLUDED.parent_code,
                     sort_order = EXCLUDED.sort_order,
                     ttl_hours = EXCLUDED.ttl_hours,
                     enabled = true"""
            ).bindparams(code=code, name=name, parent=parent, sort_order=order, ttl=ttl)
        )
    op.execute(
        "UPDATE knowledge_category SET ttl_hours = NULL "
        "WHERE code IN ('destination','travel_guide','food_lodging_transport','travel_experience','travel_news')"
    )

    # Retag every chunk in one statement per source code.  Check both fields so
    # a chunk with only a legacy sub_category is migrated as well as one with
    # only a legacy category.
    for old_code, (parent, leaf) in _MAPPING.items():
        op.execute(
            sa.text(
                """UPDATE knowledge_chunk
                   SET metadata = metadata || jsonb_build_object(
                       'category', :parent, 'sub_category', :leaf)
                   WHERE metadata->>'sub_category' = :old_code
                      OR metadata->>'category' = :old_code"""
            ).bindparams(parent=parent, leaf=leaf, old_code=old_code)
        )

    for parent, leaf in _ROOT_DEFAULTS.items():
        op.execute(
            sa.text(
                """UPDATE knowledge_chunk
                   SET metadata = metadata || jsonb_build_object(
                       'category', :parent, 'sub_category', :leaf)
                   WHERE metadata->>'category' = :parent
                     AND COALESCE(metadata->>'sub_category', '') = ''"""
            ).bindparams(parent=parent, leaf=leaf)
        )

    # Null/general records are retained, but put into the broad destination
    # bucket instead of recreating the removed 综合 category.
    op.execute(
        """UPDATE knowledge_chunk
           SET metadata = metadata || '{"category":"destination","sub_category":"destination_info"}'::jsonb
           WHERE (metadata->>'sub_category' IN ('', 'general', '未分类')
                  AND COALESCE(metadata->>'category', '') IN ('', 'general', '未分类'))
              OR (metadata->>'sub_category' IS NULL AND metadata->>'category' IS NULL)"""
    )

    old_codes = ", ".join("'" + code.replace("'", "''") + "'" for code in _OBSOLETE_CODES)
    op.execute(f"DELETE FROM knowledge_category WHERE code IN ({old_codes})")


def downgrade() -> None:
    # Data is intentionally not split back into the old semantic leaves.  The
    # old rows can be restored by 0002 if a rollback is required; preserving
    # compact metadata is safer than guessing a document's former subtype.
    op.execute(
        "DELETE FROM knowledge_category WHERE code IN "
        "('destination_info','trip_plans','accommodation','practical_tips','notices_events','travel_updates')"
    )
