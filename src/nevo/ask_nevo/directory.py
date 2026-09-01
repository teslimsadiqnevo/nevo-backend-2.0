from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nevo.ai_gateway.privacy import AiPrivacyGuard
from nevo.db.models.account import Class, StudentClassEnrollment, User
from nevo.db.models.teacher_assignment import TeacherClassAssignment
from nevo.domain.accounts.vocabulary import UserRole, UserStatus


@dataclass(frozen=True, slots=True)
class DirectoryEntry:
    student_id: UUID
    pseudonym: str
    display_name: str


class PseudonymDirectory:
    """Two-way map between a learner and the pseudonym the model sees.

    The privacy guard replaces roster names before a prompt reaches the
    provider, so the model's only handle on a learner is their pseudonym. For
    a tool to act on that handle it has to be resolvable back to a record -
    but only within the set of learners the asking user is allowed to see.

    The map is therefore built *from the actor's accessible set*, never by
    inverting a pseudonym against the whole school. A pseudonym for a learner
    the actor cannot reach simply is not in the map, which makes cross-tenant
    resolution structurally impossible rather than something to remember to
    check.

    Built per request and held in memory. Nothing is persisted, so a stored
    transcript cannot be re-identified from it later.
    """

    def __init__(self, entries: tuple[DirectoryEntry, ...]) -> None:
        self._entries = entries
        self._by_pseudonym = {entry.pseudonym.casefold(): entry for entry in entries}
        self._by_id = {entry.student_id: entry for entry in entries}

    @classmethod
    async def for_actor(cls, session: AsyncSession, actor: User) -> "PseudonymDirectory":
        students = await _accessible_students(session, actor)
        entries = tuple(
            DirectoryEntry(
                student_id=student.id,
                pseudonym=AiPrivacyGuard.pseudonym(student.id),
                display_name=_display_name(student),
            )
            for student in students
        )
        return cls(entries)

    @property
    def entries(self) -> tuple[DirectoryEntry, ...]:
        return self._entries

    def resolve(self, pseudonym: str) -> DirectoryEntry | None:
        """Pseudonym to learner, or None when it is outside the actor's reach."""
        return self._by_pseudonym.get(pseudonym.strip().casefold())

    def pseudonym_for(self, student_id: UUID) -> str | None:
        entry = self._by_id.get(student_id)
        return entry.pseudonym if entry else None

    def rehydrate(self, text: str) -> str:
        """Put real names back, on the way out to the user only.

        Longest pseudonyms first so no entry can be partially replaced by a
        shorter one that happens to be a prefix.
        """
        result = text
        for entry in sorted(self._entries, key=lambda item: len(item.pseudonym), reverse=True):
            result = result.replace(entry.pseudonym, entry.display_name)
        return result


async def _accessible_students(session: AsyncSession, actor: User) -> list[User]:
    """Every learner this actor may ask about. The set, derived once."""
    if actor.role is UserRole.STUDENT:
        return [actor]
    if actor.school_id is None:
        return []
    query = select(User).where(
        User.school_id == actor.school_id,
        User.role == UserRole.STUDENT,
        User.status != UserStatus.DEACTIVATED,
    )
    if actor.role is UserRole.TEACHER:
        query = (
            query.join(
                StudentClassEnrollment,
                StudentClassEnrollment.student_id == User.id,
            )
            .join(
                TeacherClassAssignment,
                TeacherClassAssignment.class_id == StudentClassEnrollment.class_id,
            )
            .where(
                TeacherClassAssignment.teacher_id == actor.id,
                TeacherClassAssignment.removed_at.is_(None),
            )
            .distinct()
        )
    return list((await session.scalars(query)).all())


async def accessible_classes(session: AsyncSession, actor: User) -> list[Class]:
    """Classes this actor may ask about, by the same derive-then-filter rule."""
    if actor.school_id is None or actor.role is UserRole.STUDENT:
        return []
    query = select(Class).where(
        Class.school_id == actor.school_id,
        Class.archived_at.is_(None),
    )
    if actor.role is UserRole.TEACHER:
        query = (
            query.join(
                TeacherClassAssignment,
                TeacherClassAssignment.class_id == Class.id,
            )
            .where(
                TeacherClassAssignment.teacher_id == actor.id,
                TeacherClassAssignment.removed_at.is_(None),
            )
            .distinct()
        )
    return list((await session.scalars(query.order_by(Class.name))).all())


def _display_name(user: User) -> str:
    return " ".join(part for part in (user.first_name, user.last_name) if part) or "This learner"
