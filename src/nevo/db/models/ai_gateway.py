import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from nevo.db.base import Base
from nevo.domain.ai_gateway.vocabulary import (
    AiCallStatus,
    AiProviderName,
    AiService,
)

ai_service_enum = Enum(
    AiService,
    name="ai_service",
    values_callable=lambda enum: [item.value for item in enum],
)
ai_call_status_enum = Enum(
    AiCallStatus,
    name="ai_call_status",
    values_callable=lambda enum: [item.value for item in enum],
)
ai_provider_enum = Enum(
    AiProviderName,
    name="ai_provider",
    values_callable=lambda enum: [item.value for item in enum],
)


class AiPromptTemplate(Base):
    __tablename__ = "ai_prompt_templates"
    __table_args__ = (
        UniqueConstraint(
            "name",
            "version",
            name="uq_ai_prompt_templates_name_version",
        ),
        Index(
            "uq_ai_prompt_templates_active_name",
            "name",
            unique=True,
            postgresql_where=text("active"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )
    service: Mapped[AiService] = mapped_column(ai_service_enum, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    system_template: Mapped[str] = mapped_column(Text, nullable=False)
    user_template: Mapped[str] = mapped_column(Text, nullable=False)
    required_variables: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
    )
    active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class AiGatewayCall(Base):
    __tablename__ = "ai_gateway_calls"
    __table_args__ = (
        Index(
            "ix_ai_gateway_calls_service_created_at",
            "service",
            "created_at",
        ),
        Index(
            "ix_ai_gateway_calls_school_created_at",
            "school_id",
            "created_at",
        ),
        Index("ix_ai_gateway_calls_lesson", "lesson_id", "created_at"),
        Index("ix_ai_gateway_calls_student_lesson", "student_id", "lesson_id"),
        CheckConstraint(
            "input_tokens >= 0 AND output_tokens >= 0 AND thought_tokens >= 0",
            name="token_counts_non_negative",
        ),
        CheckConstraint(
            "latency_ms >= 0 AND estimated_cost_usd >= 0",
            name="performance_values_non_negative",
        ),
        CheckConstraint(
            "(status = 'fallback') = fallback_used",
            name="fallback_status_matches_flag",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )
    school_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("schools.id", ondelete="SET NULL"),
        nullable=True,
    )
    requester_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    student_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    prompt_template_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ai_prompt_templates.id", ondelete="RESTRICT"),
        nullable=False,
    )
    #: Which lesson this call was for, where there is one.
    #:
    #: Without it, "what did one learner's lesson cost" could only be asked of
    #: a time window, and the expensive calls are lesson preparation, which
    #: happens at upload with no learner in the picture at all. Lydia,
    #: 20 November: everything about pricing is blocked on that number. The
    #: value was already reaching the gateway on the safety context and was
    #: simply not recorded. Null for a call that belongs to no lesson, such as
    #: a learner's Ask Nevo question. L2.
    lesson_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("lessons.id", ondelete="SET NULL"),
        nullable=True,
    )
    service: Mapped[AiService] = mapped_column(ai_service_enum, nullable=False)
    priority: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    provider: Mapped[AiProviderName] = mapped_column(
        ai_provider_enum,
        nullable=False,
    )
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[AiCallStatus] = mapped_column(
        ai_call_status_enum,
        nullable=False,
    )
    input_tokens: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    output_tokens: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    thought_tokens: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    #: Cache writes and cache reads, kept because the cost depends on them -
    #: a write is 1.25x a fresh input token and a read is a tenth of one - and
    #: because without them there is no way to tell whether prompt caching is
    #: working at all. The cost formula already used these; nothing stored
    #: them, so the question "are we getting cache hits" had no answer. L2/L6.
    cache_creation_input_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    cache_read_input_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    estimated_cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(14, 8),
        nullable=False,
        default=Decimal("0"),
        server_default=text("0"),
    )
    compliance_retries: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    fallback_used: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    error_code: Mapped[str | None] = mapped_column(
        String(80),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
