"""Keep Ask Nevo conversations, so a chat can be reopened.

Revision ID: 20260909_0048
Revises: 20260909_0047
Create Date: 2026-09-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260909_0048"
down_revision: str | Sequence[str] | None = "20260909_0047"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

author_enum = postgresql.ENUM("asker", "nevo", name="ask_nevo_message_author")
#: The column reference must not try to create the type a second time.
author_column = postgresql.ENUM(name="ask_nevo_message_author", create_type=False)


def upgrade() -> None:
    # Interactions recorded that a question happened and what category it fell
    # into, never the words. Nothing could be shown back to the person who
    # asked, and a follow-up had no first turn to follow.
    author_enum.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "ask_nevo_threads",
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "actor_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "school_id",
            sa.Uuid(),
            sa.ForeignKey("schools.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "role",
            postgresql.ENUM(name="ask_nevo_role", create_type=False),
            nullable=False,
        ),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column(
            "message_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "last_message_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_ask_nevo_threads_actor_last_message",
        "ask_nevo_threads",
        ["actor_user_id", "last_message_at"],
    )
    op.create_index(
        "ix_ask_nevo_threads_school_created",
        "ask_nevo_threads",
        ["school_id", "created_at"],
    )
    op.create_table(
        "ask_nevo_messages",
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "thread_id",
            sa.Uuid(),
            sa.ForeignKey("ask_nevo_threads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "interaction_id",
            sa.Uuid(),
            sa.ForeignKey("ask_nevo_interactions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("author", author_column, nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "blocks",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "thread_id",
            "sequence",
            name="uq_ask_nevo_messages_thread_sequence",
        ),
    )
    op.create_index(
        "ix_ask_nevo_messages_thread_sequence",
        "ask_nevo_messages",
        ["thread_id", "sequence"],
    )


def downgrade() -> None:
    op.drop_index("ix_ask_nevo_messages_thread_sequence", table_name="ask_nevo_messages")
    op.drop_table("ask_nevo_messages")
    op.drop_index("ix_ask_nevo_threads_school_created", table_name="ask_nevo_threads")
    op.drop_index("ix_ask_nevo_threads_actor_last_message", table_name="ask_nevo_threads")
    op.drop_table("ask_nevo_threads")
    author_enum.drop(op.get_bind(), checkfirst=True)
