from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from nevo.access import accessible_classes, accessible_students
from nevo.ai_gateway.privacy import AiPrivacyGuard
from nevo.db.models.account import User


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
        students = await accessible_students(session, actor)
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






def _display_name(user: User) -> str:
    return " ".join(part for part in (user.first_name, user.last_name) if part) or "This learner"


__all__ = ["DirectoryEntry", "PseudonymDirectory", "accessible_classes"]
