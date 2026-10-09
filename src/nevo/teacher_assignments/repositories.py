from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nevo.db.models.account import Class, User
from nevo.db.models.subject import ClassSubject, SchoolSubject, TeacherSubject
from nevo.db.models.teacher_assignment import (
    TeacherClassAssignment as TeacherClassAssignmentModel,
)
from nevo.domain.accounts.vocabulary import UserRole, UserStatus
from nevo.domain.teacher_assignments.vocabulary import (
    TeacherAssignmentRole,
    TeacherAssignmentSource,
)
from nevo.teacher_assignments.entities import (
    AssignedClass,
    AssignedTeacher,
    TeacherClassAssignment,
)
from nevo.teacher_assignments.errors import (
    AssignmentConflictError,
    AssignmentNotFoundError,
    ClassNotFoundError,
    PrimaryTeacherExistsError,
    SubjectNotOnClassError,
    SubjectNotOnTeacherError,
    SubjectRequiredError,
    TeacherNotFoundError,
)


class SqlAlchemyTeacherAssignmentRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def assign(
        self,
        *,
        school_id: UUID,
        teacher_id: UUID,
        class_id: UUID,
        role: TeacherAssignmentRole,
        source: TeacherAssignmentSource,
        source_reference: str | None,
        assigned_by_user_id: UUID | None,
        assigned_at: datetime,
        school_subject_id: UUID | None = None,
    ) -> TeacherClassAssignment:
        async with self._sessions.begin() as session:
            await self._lock_class(session, school_id, class_id)
            await self._require_teacher(session, school_id, teacher_id)
            await self._require_subject_on_both(
                session,
                teacher_id=teacher_id,
                class_id=class_id,
                school_subject_id=school_subject_id,
            )

            existing = await session.scalar(
                select(TeacherClassAssignmentModel)
                .where(
                    TeacherClassAssignmentModel.school_id == school_id,
                    TeacherClassAssignmentModel.teacher_id == teacher_id,
                    TeacherClassAssignmentModel.class_id == class_id,
                    # Per subject, because a teacher can hold the same class
                    # for two of them and those are two assignments.
                    TeacherClassAssignmentModel.school_subject_id == school_subject_id,
                    TeacherClassAssignmentModel.removed_at.is_(None),
                )
                .with_for_update()
            )
            if existing is not None:
                if existing.role is role:
                    return self._assignment(existing)
                raise AssignmentConflictError

            if role is TeacherAssignmentRole.PRIMARY:
                await self._ensure_primary_available(
                    session,
                    school_id=school_id,
                    class_id=class_id,
                )

            assignment = TeacherClassAssignmentModel(
                id=uuid4(),
                school_id=school_id,
                teacher_id=teacher_id,
                class_id=class_id,
                role=role,
                school_subject_id=school_subject_id,
                source=source,
                source_reference=source_reference,
                assigned_by_user_id=assigned_by_user_id,
                assigned_at=assigned_at,
            )
            session.add(assignment)
            await session.flush()
            return self._assignment(assignment)

    @staticmethod
    async def _require_subject_on_both(
        session: AsyncSession,
        *,
        teacher_id: UUID,
        class_id: UUID,
        school_subject_id: UUID | None,
    ) -> None:
        """The one rule that keeps the two subject lists honest.

        An assignment is only accepted where the subject sits on the teacher's
        subjects and on that class's scheme of work. Neither list is widened as
        a side effect: a teacher's subjects are a fact about that person, and a
        class's are the school's statement about what it teaches. Where they
        disagree, the school has a setup gap, and the refusal is where they
        find it - at the moment somebody assigns a teacher, rather than a term
        later when a report has nothing to group by.
        """

        if school_subject_id is None:
            raise SubjectRequiredError
        on_teacher = await session.scalar(
            select(TeacherSubject.id).where(
                TeacherSubject.teacher_id == teacher_id,
                TeacherSubject.school_subject_id == school_subject_id,
            )
        )
        if on_teacher is None:
            raise SubjectNotOnTeacherError
        on_class = await session.scalar(
            select(ClassSubject.id).where(
                ClassSubject.class_id == class_id,
                ClassSubject.school_subject_id == school_subject_id,
            )
        )
        if on_class is None:
            raise SubjectNotOnClassError

    async def reassign(
        self,
        *,
        school_id: UUID,
        assignment_id: UUID,
        new_teacher_id: UUID,
        role: TeacherAssignmentRole | None,
        assigned_by_user_id: UUID,
        assigned_at: datetime,
    ) -> TeacherClassAssignment:
        async with self._sessions.begin() as session:
            current = await session.scalar(
                select(TeacherClassAssignmentModel).where(
                    TeacherClassAssignmentModel.id == assignment_id,
                    TeacherClassAssignmentModel.school_id == school_id,
                    TeacherClassAssignmentModel.removed_at.is_(None),
                )
            )
            if current is None:
                raise AssignmentNotFoundError

            await self._lock_class(session, school_id, current.class_id)
            current = await session.scalar(
                select(TeacherClassAssignmentModel)
                .where(
                    TeacherClassAssignmentModel.id == assignment_id,
                    TeacherClassAssignmentModel.school_id == school_id,
                    TeacherClassAssignmentModel.removed_at.is_(None),
                )
                .with_for_update()
            )
            if current is None:
                raise AssignmentNotFoundError

            await self._require_teacher(session, school_id, new_teacher_id)
            next_role = role or current.role
            if current.teacher_id == new_teacher_id and current.role is next_role:
                return self._assignment(current)

            duplicate = await session.scalar(
                select(TeacherClassAssignmentModel.id)
                .where(
                    TeacherClassAssignmentModel.school_id == school_id,
                    TeacherClassAssignmentModel.teacher_id == new_teacher_id,
                    TeacherClassAssignmentModel.class_id == current.class_id,
                    TeacherClassAssignmentModel.removed_at.is_(None),
                    TeacherClassAssignmentModel.id != current.id,
                )
                .limit(1)
            )
            if duplicate is not None:
                raise AssignmentConflictError
            if next_role is TeacherAssignmentRole.PRIMARY:
                await self._ensure_primary_available(
                    session,
                    school_id=school_id,
                    class_id=current.class_id,
                    excluding_assignment_id=current.id,
                )

            await session.execute(
                update(TeacherClassAssignmentModel)
                .where(TeacherClassAssignmentModel.id == current.id)
                .values(removed_at=assigned_at)
            )
            replacement = TeacherClassAssignmentModel(
                id=uuid4(),
                school_id=school_id,
                teacher_id=new_teacher_id,
                class_id=current.class_id,
                role=next_role,
                source=TeacherAssignmentSource.MANUAL,
                assigned_by_user_id=assigned_by_user_id,
                assigned_at=assigned_at,
            )
            session.add(replacement)
            await session.flush()
            await session.execute(
                update(TeacherClassAssignmentModel)
                .where(TeacherClassAssignmentModel.id == current.id)
                .values(replaced_by_assignment_id=replacement.id)
            )
            return self._assignment(replacement)

    async def remove(
        self,
        *,
        school_id: UUID,
        assignment_id: UUID,
        removed_at: datetime,
    ) -> bool:
        async with self._sessions.begin() as session:
            result = await session.execute(
                update(TeacherClassAssignmentModel)
                .where(
                    TeacherClassAssignmentModel.id == assignment_id,
                    TeacherClassAssignmentModel.school_id == school_id,
                    TeacherClassAssignmentModel.removed_at.is_(None),
                )
                .values(removed_at=removed_at)
                .returning(TeacherClassAssignmentModel.id)
            )
            return result.scalar_one_or_none() is not None

    async def teacher_classes(
        self,
        *,
        school_id: UUID,
        teacher_id: UUID,
    ) -> list[AssignedClass]:
        async with self._sessions() as session:
            rows = (
                await session.execute(
                    select(TeacherClassAssignmentModel, Class, SchoolSubject)
                    .join(
                        Class,
                        Class.id == TeacherClassAssignmentModel.class_id,
                    )
                    .outerjoin(
                        SchoolSubject,
                        SchoolSubject.id == TeacherClassAssignmentModel.school_subject_id,
                    )
                    .where(
                        TeacherClassAssignmentModel.school_id == school_id,
                        TeacherClassAssignmentModel.teacher_id == teacher_id,
                        TeacherClassAssignmentModel.removed_at.is_(None),
                    )
                    .order_by(Class.name)
                )
            ).all()
        return [
            AssignedClass(
                assignment_id=assignment.id,
                class_id=school_class.id,
                class_name=school_class.name,
                class_code=school_class.class_code,
                role=assignment.role,
                assigned_at=assignment.assigned_at,
                subject_id=assignment.school_subject_id,
                subject=subject.name if subject else None,
            )
            for assignment, school_class, subject in rows
        ]

    async def class_teachers(
        self,
        *,
        school_id: UUID,
        class_id: UUID,
    ) -> list[AssignedTeacher]:
        async with self._sessions() as session:
            rows = (
                await session.execute(
                    select(TeacherClassAssignmentModel, User, SchoolSubject)
                    .join(
                        User,
                        User.id == TeacherClassAssignmentModel.teacher_id,
                    )
                    .outerjoin(
                        SchoolSubject,
                        SchoolSubject.id == TeacherClassAssignmentModel.school_subject_id,
                    )
                    .where(
                        TeacherClassAssignmentModel.school_id == school_id,
                        TeacherClassAssignmentModel.class_id == class_id,
                        TeacherClassAssignmentModel.removed_at.is_(None),
                    )
                    .order_by(
                        TeacherClassAssignmentModel.role,
                        User.last_name,
                        User.first_name,
                    )
                )
            ).all()
        return [
            AssignedTeacher(
                assignment_id=assignment.id,
                teacher_id=teacher.id,
                first_name=teacher.first_name,
                last_name=teacher.last_name,
                email=teacher.email,
                role=assignment.role,
                assigned_at=assignment.assigned_at,
                subject_id=assignment.school_subject_id,
                subject=subject.name if subject else None,
            )
            for assignment, teacher, subject in rows
        ]

    async def is_teacher_assigned(
        self,
        *,
        school_id: UUID,
        teacher_id: UUID,
        class_id: UUID,
    ) -> bool:
        async with self._sessions() as session:
            assignment_id = await session.scalar(
                select(TeacherClassAssignmentModel.id)
                .where(
                    TeacherClassAssignmentModel.school_id == school_id,
                    TeacherClassAssignmentModel.teacher_id == teacher_id,
                    TeacherClassAssignmentModel.class_id == class_id,
                    TeacherClassAssignmentModel.removed_at.is_(None),
                )
                .limit(1)
            )
        return assignment_id is not None

    @staticmethod
    async def _lock_class(
        session: AsyncSession,
        school_id: UUID,
        class_id: UUID,
    ) -> None:
        school_class = await session.scalar(
            select(Class.id)
            .where(
                Class.id == class_id,
                Class.school_id == school_id,
            )
            .with_for_update()
        )
        if school_class is None:
            raise ClassNotFoundError

    @staticmethod
    async def _require_teacher(
        session: AsyncSession,
        school_id: UUID,
        teacher_id: UUID,
    ) -> None:
        teacher = await session.scalar(
            select(User.id)
            .where(
                User.id == teacher_id,
                User.school_id == school_id,
                User.role == UserRole.TEACHER,
                User.status == UserStatus.ACTIVE,
            )
            .with_for_update()
        )
        if teacher is None:
            raise TeacherNotFoundError

    @staticmethod
    async def _ensure_primary_available(
        session: AsyncSession,
        *,
        school_id: UUID,
        class_id: UUID,
        excluding_assignment_id: UUID | None = None,
    ) -> None:
        statement = select(TeacherClassAssignmentModel.id).where(
            TeacherClassAssignmentModel.school_id == school_id,
            TeacherClassAssignmentModel.class_id == class_id,
            TeacherClassAssignmentModel.role == TeacherAssignmentRole.PRIMARY,
            TeacherClassAssignmentModel.removed_at.is_(None),
        )
        if excluding_assignment_id is not None:
            statement = statement.where(TeacherClassAssignmentModel.id != excluding_assignment_id)
        existing = await session.scalar(statement.limit(1))
        if existing is not None:
            raise PrimaryTeacherExistsError

    @staticmethod
    def _assignment(
        assignment: TeacherClassAssignmentModel,
    ) -> TeacherClassAssignment:
        return TeacherClassAssignment(
            id=assignment.id,
            school_id=assignment.school_id,
            teacher_id=assignment.teacher_id,
            class_id=assignment.class_id,
            role=assignment.role,
            source=assignment.source,
            assigned_at=assignment.assigned_at,
            removed_at=assignment.removed_at,
            replaced_by_assignment_id=assignment.replaced_by_assignment_id,
            school_subject_id=assignment.school_subject_id,
        )
