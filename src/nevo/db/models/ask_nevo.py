import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from nevo.db.base import Base
from nevo.domain.ask_nevo.vocabulary import (
    AskNevoMessageAuthor,
    AskNevoQuestionCategory,
    AskNevoRole,
)

ask_nevo_role_enum = Enum(
    AskNevoRole,
    name="ask_nevo_role",
    values_callable=lambda enum: [item.value for item in enum],
)
ask_nevo_question_category_enum = Enum(
    AskNevoQuestionCategory,
    name="ask_nevo_question_category",
    values_callable=lambda enum: [item.value for item in enum],
)


class AskNevoInteraction(Base):
    __tablename__ = "ask_nevo_interactions"
    __table_args__ = (
        Index("ix_ask_nevo_interactions_actor_created", "actor_user_id", "created_at"),
        Index("ix_ask_nevo_interactions_role_created", "role", "created_at"),
        Index("ix_ask_nevo_interactions_category_created", "question_category", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    actor_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    role: Mapped[AskNevoRole] = mapped_column(ask_nevo_role_enum, nullable=False)
    current_page: Mapped[str] = mapped_column(String(120), nullable=False)
    context_ids: Mapped[dict[str, str | None]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    question_category: Mapped[AskNevoQuestionCategory] = mapped_column(
        ask_nevo_question_category_enum,
        nullable=False,
    )
    ai_gateway_call_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("ai_gateway_calls.id", ondelete="SET NULL"),
        nullable=True,
    )
    response_helpful: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


ask_nevo_message_author_enum = Enum(
    AskNevoMessageAuthor,
    name="ask_nevo_message_author",
    values_callable=lambda enum: [item.value for item in enum],
)


class AskNevoThread(Base):
    """One conversation, so a follow-up has something to follow.

    Every question used to stand alone: thread_id was accepted and written
    into a JSON blob nothing grouped by, so a learner could not say "explain
    that again more simply" and be understood.
    """

    __tablename__ = "ask_nevo_threads"
    __table_args__ = (
        Index("ix_ask_nevo_threads_actor_last_message", "actor_user_id", "last_message_at"),
        Index("ix_ask_nevo_threads_school_created", "school_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    actor_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    #: Denormalised so retention can find a thread's school without joining
    #: through a user who may since have been anonymised.
    school_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("schools.id", ondelete="CASCADE"),
        nullable=True,
    )
    role: Mapped[AskNevoRole] = mapped_column(ask_nevo_role_enum, nullable=False)
    #: The opening question, trimmed. What a list of past chats shows.
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    message_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    last_message_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    #: Set when the asker deletes the chat. The row goes at the next sweep;
    #: until then nothing reads it.
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class AskNevoMessage(Base):
    """One turn. Stored as it was shown, so a chat renders back identically."""

    __tablename__ = "ask_nevo_messages"
    __table_args__ = (
        UniqueConstraint("thread_id", "sequence", name="uq_ask_nevo_messages_thread_sequence"),
        Index("ix_ask_nevo_messages_thread_sequence", "thread_id", "sequence"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    thread_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("ask_nevo_threads.id", ondelete="CASCADE"),
        nullable=False,
    )
    #: Links the answer back to its telemetry. Null on the asker's own turn.
    interaction_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("ask_nevo_interactions.id", ondelete="SET NULL"),
        nullable=True,
    )
    author: Mapped[AskNevoMessageAuthor] = mapped_column(
        ask_nevo_message_author_enum,
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    #: The structured blocks the client rendered, so re-opening a chat shows
    #: what was shown rather than a re-derivation that may have drifted.
    blocks: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
