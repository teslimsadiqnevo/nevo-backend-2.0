import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from nevo.db.base import Base
from nevo.domain.accounts.vocabulary import (
    RosterSyncIssueStatus,
    RosterSyncStatus,
    SsoConnectionStatus,
    SsoProvider,
)

sso_provider_enum = Enum(
    SsoProvider,
    name="sso_provider",
    values_callable=lambda enum: [item.value for item in enum],
)
roster_sync_status_enum = Enum(
    RosterSyncStatus,
    name="roster_sync_status",
    values_callable=lambda enum: [item.value for item in enum],
)
roster_sync_issue_status_enum = Enum(
    RosterSyncIssueStatus,
    name="roster_sync_issue_status",
    values_callable=lambda enum: [item.value for item in enum],
)
sso_connection_status_enum = Enum(
    SsoConnectionStatus,
    name="sso_connection_status",
    values_callable=lambda enum: [item.value for item in enum],
)


class SchoolSsoConfiguration(Base):
    __tablename__ = "school_sso_configurations"
    __table_args__ = (
        Index(
            "uq_school_sso_configurations_school_provider",
            "school_id",
            "provider",
            unique=True,
        ),
        Index(
            "ix_school_sso_configurations_slug_provider",
            "school_url_slug",
            "provider",
        ),
        CheckConstraint(
            "(connection_status = 'disconnected') = "
            "(disconnected_at IS NOT NULL)",
            name="disconnected_matches_timestamp",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    school_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("schools.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[SsoProvider] = mapped_column(sso_provider_enum, nullable=False)
    tenant_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    hosted_domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    client_id: Mapped[str] = mapped_column(String(255), nullable=False)
    client_secret_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    oauth_credential_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    school_url_slug: Mapped[str] = mapped_column(String(100), nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )
    connection_status: Mapped[SsoConnectionStatus] = mapped_column(
        sso_connection_status_enum,
        nullable=False,
        default=SsoConnectionStatus.CONNECTED,
        server_default=SsoConnectionStatus.CONNECTED.value,
    )
    # Provider-reported reason the connection needs attention, kept in plain
    # language because it reaches a non-technical administrator.
    last_connection_error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    connection_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    reauthorised_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    next_scheduled_sync_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    # Disconnecting is a soft disable. Accounts survive so that a school can
    # reconnect, or fall back to email/password, without losing anyone.
    disconnected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    disconnected_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class RosterSyncRun(Base):
    __tablename__ = "roster_sync_runs"
    __table_args__ = (
        Index("ix_roster_sync_runs_school_started", "school_id", "started_at"),
        Index("ix_roster_sync_runs_provider_started", "provider", "started_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    school_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("schools.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[SsoProvider] = mapped_column(sso_provider_enum, nullable=False)
    status: Mapped[RosterSyncStatus] = mapped_column(
        roster_sync_status_enum,
        nullable=False,
    )
    imported_students: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    imported_teachers: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    missing_teacher_class_mappings: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    # Set only on a failed run. Plain language: the admin dashboard shows it
    # verbatim to a non-technical administrator.
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # True when an administrator pressed sync rather than the schedule firing.
    triggered_manually: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    triggered_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class RosterSyncIssue(Base):
    __tablename__ = "roster_sync_issues"
    __table_args__ = (
        Index("ix_roster_sync_issues_school_status", "school_id", "status"),
        Index("ix_roster_sync_issues_run", "roster_sync_run_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    roster_sync_run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("roster_sync_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    school_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("schools.id", ondelete="CASCADE"),
        nullable=False,
    )
    external_reference: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    # What the administrator can actually do about it. Usually a permission to
    # re-grant at the identity provider.
    resolution_hint: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[RosterSyncIssueStatus] = mapped_column(
        roster_sync_issue_status_enum,
        nullable=False,
        default=RosterSyncIssueStatus.OPEN,
        server_default=RosterSyncIssueStatus.OPEN.value,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
