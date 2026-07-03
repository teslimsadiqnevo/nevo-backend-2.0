import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from nevo.db.base import Base
from nevo.domain.teacher_assignments.vocabulary import (
    TeacherAssignmentRole,
    TeacherAssignmentSource,
)

teacher_assignment_role_enum = Enum(
    TeacherAssignmentRole,
    name="teacher_assignment_role",
    values_callable=lambda enum: [item.value for item in enum],
)
teacher_assignment_source_enum = Enum(
    TeacherAssignmentSource,
    name="teacher_assignment_source",
    values_callable=lambda enum: [item.value for item in enum],
)


class TeacherClassAssignment(Base):
    __tablename__ = "teacher_class_assignments"
    __table_args__ = (
        CheckConstraint(
            "removed_at IS NULL OR removed_at >= assigned_at",
            name="removed_after_assignment",
        ),
        Index(
            "ix_teacher_class_assignments_teacher_active",
            "teacher_id",
            "removed_at",
        ),
        Index(
            "ix_teacher_class_assignments_class_active",
            "class_id",
            "removed_at",
        ),
        Index(
            "uq_teacher_class_assignments_active_pair",
            "teacher_id",
            "class_id",
            unique=True,
            postgresql_where=text("removed_at IS NULL"),
        ),
        Index(
            "uq_teacher_class_assignments_active_primary",
            "class_id",
            unique=True,
            postgresql_where=text(
                "role = 'primary' AND removed_at IS NULL"
            ),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    school_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("schools.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    teacher_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    class_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("classes.id", ondelete="RESTRICT"),
        nullable=False,
    )
    role: Mapped[TeacherAssignmentRole] = mapped_column(
        teacher_assignment_role_enum,
        nullable=False,
    )
    source: Mapped[TeacherAssignmentSource] = mapped_column(
        teacher_assignment_source_enum,
        nullable=False,
        default=TeacherAssignmentSource.MANUAL,
        server_default=TeacherAssignmentSource.MANUAL.value,
    )
    source_reference: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    assigned_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    removed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    replaced_by_assignment_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("teacher_class_assignments.id", ondelete="SET NULL"),
        nullable=True,
    )
