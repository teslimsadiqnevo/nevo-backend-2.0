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
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from nevo.db.base import Base
from nevo.domain.accounts.vocabulary import (
    RosterSyncIssueStatus,
    RosterSyncStatus,
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
    school_url_slug: Mapped[str] = mapped_column(String(100), nullable=False)
    enabled: Mapped[bool] = mapped_column(
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
