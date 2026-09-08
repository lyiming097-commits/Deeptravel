"""Create the initial DeepTravel persistence schema."""

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "knowledge_document",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("file_name", sa.Text(), nullable=False),
        sa.Column("file_hash", sa.String(64)),
        sa.Column("media_type", sa.String(100)),
        sa.Column("object_key", sa.Text()),
        sa.Column("source_url", sa.Text()),
        sa.Column("status", sa.String(30), nullable=False, server_default="UPLOADED"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("error_message", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "uq_knowledge_document_file_hash",
        "knowledge_document",
        ["file_hash"],
        unique=True,
        postgresql_where=sa.text("file_hash IS NOT NULL"),
    )
    op.create_table(
        "knowledge_chunk",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "document_id",
            sa.Uuid(),
            sa.ForeignKey("knowledge_document.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chunk_index", sa.Integer()),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64)),
        sa.Column(
            "metadata", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("embedding", Vector(1024)),
        sa.Column("token_count", sa.Integer()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "uq_knowledge_chunk_document_index",
        "knowledge_chunk",
        ["document_id", "chunk_index"],
        unique=True,
        postgresql_where=sa.text("chunk_index IS NOT NULL"),
    )
    op.execute(
        "CREATE INDEX idx_knowledge_chunk_embedding ON knowledge_chunk "
        "USING hnsw (embedding vector_cosine_ops)"
    )
    op.create_table(
        "chat_session",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("title", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_table(
        "chat_message",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "session_id",
            sa.Uuid(),
            sa.ForeignKey("chat_session.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "metadata", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("role IN ('user', 'assistant', 'system', 'tool')"),
    )
    op.create_index(
        "idx_chat_message_session_created",
        "chat_message",
        ["session_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_chat_message_session_created", table_name="chat_message")
    op.drop_table("chat_message")
    op.drop_table("chat_session")
    op.drop_index("idx_knowledge_chunk_embedding", table_name="knowledge_chunk")
    op.drop_index("uq_knowledge_chunk_document_index", table_name="knowledge_chunk")
    op.drop_table("knowledge_chunk")
    op.drop_index("uq_knowledge_document_file_hash", table_name="knowledge_document")
    op.drop_table("knowledge_document")
