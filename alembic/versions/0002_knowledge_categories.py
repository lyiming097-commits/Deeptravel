"""Add dynamic knowledge categories and document expiry metadata."""

import sqlalchemy as sa

from alembic import op

revision = "0002_knowledge_categories"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

_ROWS = [
    ("destination", "目的地", None, 10, None),
    ("travel_guide", "旅游攻略", None, 20, None),
    ("food_lodging_transport", "吃住行", None, 30, None),
    ("travel_experience", "旅游经验", None, 40, None),
    ("travel_news", "旅游资讯", None, 50, 168),
    ("attraction", "景点", "destination", 10, None),
    ("city_intro", "城市介绍", "destination", 20, None),
    ("culture_history", "文化历史", "destination", 30, None),
    ("one_day", "一日游", "travel_guide", 10, None),
    ("three_day", "三日游", "travel_guide", 20, None),
    ("family_trip", "亲子游", "travel_guide", 30, None),
    ("self_drive", "自驾游", "travel_guide", 40, None),
    ("food", "美食", "food_lodging_transport", 10, None),
    ("hotel", "酒店推荐", "food_lodging_transport", 20, None),
    ("lodging_experience", "住宿经验", "food_lodging_transport", 30, None),
    ("transportation", "交通指南", "food_lodging_transport", 40, None),
    ("avoid_pitfalls", "避坑指南", "travel_experience", 10, None),
    ("budget", "预算规划", "travel_experience", 20, None),
    ("faq", "FAQ问答", "travel_experience", 30, None),
    ("photography", "摄影打卡", "travel_experience", 40, None),
    ("opening", "景区公告", "travel_news", 10, 72),
    ("festival", "节假日活动", "travel_news", 20, 168),
    ("traffic_update", "交通动态", "travel_news", 30, 72),
    ("news", "文旅新闻", "travel_news", 40, 336),
]


def upgrade() -> None:
    op.execute("""CREATE TABLE IF NOT EXISTS knowledge_category (
      code VARCHAR(80) PRIMARY KEY, name VARCHAR(120) NOT NULL,
      parent_code VARCHAR(80) REFERENCES knowledge_category(code) ON DELETE CASCADE,
      sort_order INTEGER NOT NULL DEFAULT 0, enabled BOOLEAN NOT NULL DEFAULT TRUE,
      ttl_hours INTEGER, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now())""")
    op.execute("ALTER TABLE knowledge_document ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ")
    op.execute("CREATE INDEX IF NOT EXISTS idx_knowledge_chunk_metadata ON knowledge_chunk USING gin (metadata)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_knowledge_document_expires_at ON knowledge_document(expires_at) WHERE expires_at IS NOT NULL")
    for code, name, parent, order, ttl in _ROWS:
        op.execute(
            sa.text(
                "INSERT INTO knowledge_category (code, name, parent_code, sort_order, ttl_hours) "
                "VALUES (:code, :name, :parent, :order, :ttl) "
                "ON CONFLICT (code) DO UPDATE SET "
                "name = EXCLUDED.name, parent_code = EXCLUDED.parent_code, "
                "sort_order = EXCLUDED.sort_order, ttl_hours = EXCLUDED.ttl_hours, enabled = true"
            ).bindparams(code=code, name=name, parent=parent, order=order, ttl=ttl)
        )
    # Legacy general documents remain searchable but are mapped to a useful
    # top-level category instead of exposing the removed 综合分类.
    op.execute(
        "UPDATE knowledge_chunk SET metadata = metadata || '{\"category\":\"destination\",\"sub_category\":\"city_intro\"}'::jsonb "
        "WHERE metadata->>'category' IN ('general', '未分类') OR metadata->>'category' IS NULL"
    )
    op.execute("DELETE FROM knowledge_category WHERE code = 'general'")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_knowledge_document_expires_at")
    op.execute("DROP INDEX IF EXISTS idx_knowledge_chunk_metadata")
    op.drop_column("knowledge_document", "expires_at")
    op.drop_table("knowledge_category")
