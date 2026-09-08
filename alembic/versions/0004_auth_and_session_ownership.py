"""Add authentication and per-user chat-session ownership.

These tables and columns existed in the development database before they were
captured by Alembic.  The migration is deliberately idempotent so it upgrades
both a clean Render database and an existing local database safely.
"""

from alembic import op

revision = "0004_auth_session_ownership"
down_revision = "0003_compact_categories"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS app_user (
          id UUID PRIMARY KEY,
          username VARCHAR(64) NOT NULL UNIQUE,
          display_name VARCHAR(120),
          password_hash TEXT NOT NULL,
          role VARCHAR(20) NOT NULL DEFAULT 'user',
          is_active BOOLEAN NOT NULL DEFAULT TRUE,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CONSTRAINT app_user_role_check CHECK (role IN ('user', 'admin'))
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_app_user_single_admin "
        "ON app_user(role) WHERE role = 'admin'"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS auth_session (
          token_hash VARCHAR(64) PRIMARY KEY,
          user_id UUID NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
          expires_at TIMESTAMPTZ NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_auth_session_user ON auth_session(user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_auth_session_expiry ON auth_session(expires_at)")

    op.execute("ALTER TABLE chat_session ADD COLUMN IF NOT EXISTS user_id UUID")
    op.execute(
        "ALTER TABLE chat_session ADD COLUMN IF NOT EXISTS scene_code "
        "VARCHAR(50) NOT NULL DEFAULT 'TRAVEL_PLAN'"
    )
    op.execute(
        """
        DO $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname = 'fk_chat_session_user'
              AND conrelid = 'chat_session'::regclass
          ) THEN
            ALTER TABLE chat_session
              ADD CONSTRAINT fk_chat_session_user
              FOREIGN KEY (user_id) REFERENCES app_user(id) ON DELETE CASCADE;
          END IF;
        END $$
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_chat_session_user_updated "
        "ON chat_session(user_id, updated_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_chat_session_user_scene_updated "
        "ON chat_session(user_id, scene_code, updated_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_chat_session_user_scene_updated")
    op.execute("DROP INDEX IF EXISTS idx_chat_session_user_updated")
    op.execute("ALTER TABLE chat_session DROP CONSTRAINT IF EXISTS fk_chat_session_user")
    op.execute("ALTER TABLE chat_session DROP COLUMN IF EXISTS scene_code")
    op.execute("ALTER TABLE chat_session DROP COLUMN IF EXISTS user_id")
    op.execute("DROP TABLE IF EXISTS auth_session")
    op.execute("DROP INDEX IF EXISTS uq_app_user_single_admin")
    op.execute("DROP TABLE IF EXISTS app_user")
