import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, String, Uuid, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from nevo.db.base import Base
from nevo.domain.ask_nevo.vocabulary import AskNevoQuestionCategory, AskNevoRole

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
