import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from nevo.db.base import Base
from nevo.db.models.account import TimestampMixin, user_role_enum
from nevo.domain.accounts.vocabulary import UserRole
from nevo.domain.permissions.vocabulary import PermissionScope

permission_scope_enum = Enum(
    PermissionScope,
    name="permission_scope",
    values_callable=lambda enum: [item.value for item in enum],
)


class Admin(TimestampMixin, Base):
    __tablename__ = "admins"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_admins_user_id"),
        Index("ix_admins_school_id", "school_id"),
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
    )
    school_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("schools.id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )


class AdminScopeAssignment(Base):
    __tablename__ = "admin_scope_assignments"
    __table_args__ = (
        CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= granted_at",
            name="revoked_after_grant",
        ),
        Index("ix_admin_scope_assignments_admin_active", "admin_id", "revoked_at"),
        Index(
            "uq_admin_scope_assignments_active",
            "admin_id",
            "scope",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    admin_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("admins.id", ondelete="CASCADE"),
        nullable=False,
    )
    scope: Mapped[PermissionScope] = mapped_column(
        permission_scope_enum,
        nullable=False,
    )
    granted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class AdminInvitation(Base):
    __tablename__ = "admin_invitations"
    __table_args__ = (
        CheckConstraint(
            "expires_at > created_at",
            name="expiry_after_creation",
        ),
        CheckConstraint(
            "accepted_at IS NULL OR revoked_at IS NULL",
            name="not_accepted_and_revoked",
        ),
        Index("ix_admin_invitations_expires_at", "expires_at"),
        Index(
            "uq_admin_invitations_active_user",
            "user_id",
            unique=True,
            postgresql_where=text(
                "accepted_at IS NULL AND revoked_at IS NULL"
            ),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    school_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("schools.id", ondelete="RESTRICT"),
        nullable=False,
    )
    role: Mapped[UserRole] = mapped_column(user_role_enum, nullable=False)
    token_digest: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
    )
    invited_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
