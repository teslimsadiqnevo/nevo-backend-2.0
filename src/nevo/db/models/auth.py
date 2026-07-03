import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from nevo.db.base import Base
from nevo.db.models.account import user_role_enum
from nevo.domain.accounts.vocabulary import UserRole

REVOCATION_REASONS = (
    "logout",
    "expired",
    "concurrent_login",
    "admin_revoked",
    "credential_changed",
    "user_unavailable",
)

class AuthSession(Base):
    __tablename__ = "auth_sessions"
    __table_args__ = (
        CheckConstraint(
            "expires_at > created_at",
            name="expiry_after_creation",
        ),
        CheckConstraint(
            "(revoked_at IS NULL AND revocation_reason IS NULL) OR "
            "(revoked_at IS NOT NULL AND revocation_reason IS NOT NULL)",
            name="revocation_fields_consistent",
        ),
        Index("ix_auth_sessions_user_active", "user_id", "revoked_at"),
        Index(
            "uq_auth_sessions_one_active_student",
            "user_id",
            unique=True,
            postgresql_where=text("role = 'student' AND revoked_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    role: Mapped[UserRole] = mapped_column(user_role_enum, nullable=False)
    token_digest: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    revocation_reason: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
    )
    replaced_by_session_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("auth_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )


class AuthLoginAttempt(Base):
    __tablename__ = "auth_login_attempts"
    __table_args__ = (
        Index(
            "ix_auth_login_attempts_identity_occurred",
            "identity_digest",
            "occurred_at",
        ),
        Index(
            "ix_auth_login_attempts_ip_occurred",
            "ip_digest",
            "occurred_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    identity_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    ip_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    succeeded: Mapped[bool] = mapped_column(Boolean, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class AuthAuditEvent(Base):
    __tablename__ = "auth_audit_events"
    __table_args__ = (
        Index(
            "ix_auth_audit_events_user_occurred",
            "user_id",
            "occurred_at",
        ),
        Index("ix_auth_audit_events_type_occurred", "event_type", "occurred_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("auth_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    identity_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ip_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    details: Mapped[dict[str, str] | None] = mapped_column(JSONB, nullable=True)
