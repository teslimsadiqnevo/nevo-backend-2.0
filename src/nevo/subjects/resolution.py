"""Turning what somebody typed into a subject on a school's list.

A spreadsheet column is free text, so one school will send Maths, Further
Maths and Maths Dept for two subjects and a department. Each string has to
become one row on that school's list before anything is saved against it:
accepting unresolved strings means a term of the same subject split three ways
in every report, and no way to put it back together afterwards.

Three outcomes per string. It matches one of Nevo's, it matches something the
school already has, or nobody knows yet - and the last one is held for an
administrator to settle rather than guessed at.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from nevo.db.models.subject import (
    CanonicalSubject,
    SchoolSubject,
    SubjectSpellingQuestion,
)
from nevo.domain.subjects import spelling
from nevo.domain.subjects.vocabulary import (
    SpellingAnswer,
    SubjectOrigin,
    SubjectReviewState,
)


def normalise(name: str) -> str:
    """Case and inner spacing folded, so "Maths" and " maths " are one thing."""

    return " ".join(name.split()).casefold()


@dataclass(frozen=True, slots=True)
class ResolvedSubject:
    """One column value, and what it turned out to be."""

    typed: str
    school_subject_id: UUID | None
    display_name: str | None
    origin: SubjectOrigin | None

    @property
    def resolved(self) -> bool:
        return self.school_subject_id is not None


async def display_names(session: AsyncSession, subject_ids: list[UUID]) -> dict[UUID, str]:
    """What each subject is called, canonical name winning where there is one.

    The canonical display name is what every surface renders, so the same
    subject reads identically in every school. A school's own keeps the words
    the school typed, because nobody else has a better name for it.
    """

    if not subject_ids:
        return {}
    rows = await session.execute(
        select(SchoolSubject.id, SchoolSubject.name, CanonicalSubject.display_name)
        .outerjoin(CanonicalSubject, CanonicalSubject.id == SchoolSubject.canonical_subject_id)
        .where(SchoolSubject.id.in_(subject_ids))
    )
    return {subject_id: (canonical or own) for subject_id, own, canonical in rows}


async def resolve(
    session: AsyncSession,
    *,
    school_id: UUID,
    typed: str,
) -> ResolvedSubject:
    """Match a typed subject against this school's list, then against Nevo's.

    Looks only; nothing is created. A caller that wants to add the subject
    calls ``ensure`` once an administrator has said to.
    """

    name = typed.strip()
    if not name:
        return ResolvedSubject(typed=typed, school_subject_id=None, display_name=None, origin=None)
    normalised = normalise(name)
    existing = await session.scalar(
        select(SchoolSubject).where(
            SchoolSubject.school_id == school_id,
            SchoolSubject.normalised_name == normalised,
        )
    )
    if existing is not None:
        names = await display_names(session, [existing.id])
        return ResolvedSubject(
            typed=typed,
            school_subject_id=existing.id,
            display_name=names.get(existing.id, existing.name),
            origin=existing.origin,
        )
    canonical = await session.scalar(
        select(CanonicalSubject).where(
            CanonicalSubject.display_name.ilike(name),
        )
    )
    if canonical is not None:
        # Nevo has it and the school does not yet. Still unresolved as far as
        # this function goes, because adding it to a school's list is a write.
        return ResolvedSubject(
            typed=typed,
            school_subject_id=None,
            display_name=canonical.display_name,
            origin=SubjectOrigin.CANONICAL,
        )
    return ResolvedSubject(typed=typed, school_subject_id=None, display_name=None, origin=None)


async def ensure(
    session: AsyncSession,
    *,
    school_id: UUID,
    typed: str,
    created_by_user_id: UUID | None = None,
) -> SchoolSubject:
    """Get this school's row for a subject, adding it if it has none.

    A string matching one of Nevo's becomes a canonical row for that school. A
    string nobody recognises becomes the school's own, pending review - which
    is how the canonical list grows out of real schools rather than a meeting.
    """

    name = " ".join(typed.split())
    normalised = normalise(name)
    existing = await session.scalar(
        select(SchoolSubject).where(
            SchoolSubject.school_id == school_id,
            SchoolSubject.normalised_name == normalised,
        )
    )
    if existing is not None:
        return existing
    folded = await _fold_spelling(session, school_id=school_id, typed=name)
    if folded is not None:
        return folded
    canonical = await session.scalar(
        select(CanonicalSubject).where(CanonicalSubject.display_name.ilike(name))
    )
    subject = SchoolSubject(
        school_id=school_id,
        name=name,
        normalised_name=normalised,
        origin=SubjectOrigin.CANONICAL if canonical else SubjectOrigin.SCHOOL,
        canonical_subject_id=canonical.id if canonical else None,
        # A canonical one needs no review; it is already Nevo's own word.
        review_state=SubjectReviewState.MERGED if canonical else SubjectReviewState.PENDING,
        created_by_user_id=created_by_user_id,
    )
    session.add(subject)
    await session.flush()
    return subject


async def _fold_spelling(
    session: AsyncSession, *, school_id: UUID, typed: str
) -> SchoolSubject | None:
    """Fold a second spelling of a subject this school already has into it.

    Maths arriving at a school that already has Mathematics is one subject
    written twice, and two rows would split a child's mastery across two
    knowledge graphs. So the existing row is returned, renamed to the fuller
    spelling, and the question is recorded for the classes screen to ask.
    Nothing is folded where ``possible_pair`` cannot argue for it: a subject
    Nevo has never heard of is the school's own, accepted as given, with no
    prompt. SCRUM-204.
    """

    already = await session.scalar(
        select(SubjectSpellingQuestion).where(
            SubjectSpellingQuestion.school_id == school_id,
            SubjectSpellingQuestion.normalised_other == normalise(typed),
        )
    )
    if already is not None:
        # Asked once already. A school that said "different" has its own row
        # for this spelling by now, and one that has not answered keeps the
        # fold rather than being asked twice for the same two words.
        if already.answer is SpellingAnswer.DIFFERENT and already.split_subject_id:
            return await session.get(SchoolSubject, already.split_subject_id)
        return await session.get(SchoolSubject, already.kept_subject_id)
    candidates = list(
        await session.scalars(select(SchoolSubject).where(SchoolSubject.school_id == school_id))
    )
    for candidate in candidates:
        if not spelling.possible_pair(candidate.name, typed):
            continue
        keep = spelling.fuller(candidate.name, typed)
        other = typed if keep != typed else candidate.name
        if keep != candidate.name:
            candidate.name = keep
            candidate.normalised_name = normalise(keep)
        session.add(
            SubjectSpellingQuestion(
                school_id=school_id,
                kept_subject_id=candidate.id,
                other_label=other,
                normalised_other=normalise(other),
            )
        )
        await session.flush()
        return candidate
    return None


async def subjects_for_class(session: AsyncSession, class_id: UUID) -> list[str]:
    """What this class is taught, in the names a screen should render."""

    from nevo.db.models.subject import ClassSubject

    rows = await session.execute(
        select(SchoolSubject.id)
        .join(ClassSubject, ClassSubject.school_subject_id == SchoolSubject.id)
        .where(ClassSubject.class_id == class_id)
    )
    ids = [row[0] for row in rows]
    names = await display_names(session, ids)
    return sorted(names.values())


async def subjects_for_classes(
    session: AsyncSession, class_ids: list[UUID]
) -> dict[UUID, list[str]]:
    """The same, for a page of classes, in one query rather than one each."""

    from nevo.db.models.subject import ClassSubject

    if not class_ids:
        return {}
    rows = (
        await session.execute(
            select(
                ClassSubject.class_id,
                SchoolSubject.id,
                SchoolSubject.name,
                CanonicalSubject.display_name,
            )
            .join(SchoolSubject, SchoolSubject.id == ClassSubject.school_subject_id)
            .outerjoin(CanonicalSubject, CanonicalSubject.id == SchoolSubject.canonical_subject_id)
            .where(ClassSubject.class_id.in_(class_ids))
        )
    ).all()
    grouped: dict[UUID, list[str]] = {}
    for class_id, _subject_id, own, canonical in rows:
        grouped.setdefault(class_id, []).append(canonical or own)
    return {class_id: sorted(names) for class_id, names in grouped.items()}


async def set_class_subjects(
    session: AsyncSession,
    *,
    school_id: UUID,
    class_id: UUID,
    typed: list[str],
    created_by_user_id: UUID | None = None,
) -> list[str]:
    """Replace a class's scheme of work with what the school just stated.

    Replace rather than merge: a teacher who writes a list and still sees a
    subject they did not write has no way to remove it, so a merging control
    would be lying about what it does.

    Rows are removed and added rather than the whole set rewritten, so a
    subject that stays keeps its row - and anything already filed against that
    row, including a teacher's assignment to this class for it.
    """

    from nevo.db.models.subject import ClassSubject

    wanted: dict[UUID, None] = {}
    for name in typed:
        if not name.strip():
            continue
        subject = await ensure(
            session,
            school_id=school_id,
            typed=name,
            created_by_user_id=created_by_user_id,
        )
        wanted[subject.id] = None
    held = {
        row[0]
        for row in await session.execute(
            select(ClassSubject.school_subject_id).where(ClassSubject.class_id == class_id)
        )
    }
    for subject_id in held - set(wanted):
        await session.execute(
            delete(ClassSubject).where(
                ClassSubject.class_id == class_id,
                ClassSubject.school_subject_id == subject_id,
            )
        )
    for subject_id in set(wanted) - held:
        session.add(ClassSubject(class_id=class_id, school_subject_id=subject_id))
    await session.flush()
    names = await display_names(session, list(wanted))
    return sorted(names.values())
