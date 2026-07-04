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
        CheckConstraint(
            "input_tokens >= 0 AND output_tokens >= 0 "
            "AND thought_tokens >= 0",
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
