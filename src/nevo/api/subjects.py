"""A school's subject list, and who teaches what on it.

Nevo owns a canonical list so Mathematics reads identically everywhere. A
school can add one the list does not hold, because our list covers Nigerian
secondary well and will not cover primary, Montessori or Cambridge - and a
school that cannot enter its own subject cannot use the product.

Every addition lands in a review queue with the school that made it and the
words they typed. That is how the canonical list grows out of real schools
rather than out of a meeting, and it is why a school subject can be pointed at
a canonical one later: the records reference the school's row, so repointing it
loses nothing.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import Field
from sqlalchemy import delete, select

from nevo.api.auth import PrincipalDependency
from nevo.api.dependencies import DatabaseSession
from nevo.api.product_common import require_school_actor
from nevo.api.response_models import CamelResponse
from nevo.db.models.account import User
from nevo.db.models.subject import (
    CanonicalSubject,
    ClassSubject,
    SchoolSubject,
    SubjectSpellingQuestion,
    TeacherSubject,
)
from nevo.domain.accounts.vocabulary import UserRole
from nevo.domain.subjects.vocabulary import (
    SpellingAnswer,
    SubjectOrigin,
    SubjectReviewState,
)
from nevo.subjects.resolution import display_names, ensure, normalise, resolve

router = APIRouter(prefix="/api/v1", tags=["subjects"])

ADMIN_ROLES = {UserRole.SENCO_ADMIN, UserRole.OTHER_ADMIN}

SubjectName = Annotated[str, Field(min_length=1, max_length=120)]


class CanonicalSubjectResponse(CamelResponse):
    """One of Nevo's own, for a picker."""

    id: UUID
    slug: str
    display_name: str


class SchoolSubjectResponse(CamelResponse):
    """One subject on this school's list.

    ``displayName`` is what to render: the canonical name where the row points
    at one, the school's own words otherwise. ``name`` is always the words the
    school typed, which is what the review queue shows.
    """

    id: UUID
    name: str
    display_name: str
    origin: SubjectOrigin
    review_state: SubjectReviewState
    #: True when nothing references it yet, so a screen can offer to remove it.
    removable: bool = False


class AddSubjectRequest(CamelResponse):
    name: SubjectName


class ResolvePreview(CamelResponse):
    """What a typed string would become, without writing anything.

    For the import confirmation step: a school types Maths, Further Maths and
    Maths Dept, and needs to see which of those Nevo recognises before any of
    it is saved.
    """

    typed: str
    resolved: bool
    display_name: str | None = None
    school_subject_id: UUID | None = None
    origin: SubjectOrigin | None = None


class SpellingQuestion(CamelResponse):
    """ "Maths and Mathematics, same subject or different?"

    One question, two answers, asked on the classes screen and not during
    onboarding: a class merge changes the headcount and therefore the invoice,
    a subject spelling does not, so this one waits. Until it is answered the
    two are already treated as one subject, which is the safe default - two
    subjects would split a child's mastery across two knowledge graphs and
    halve their progress for no reason.
    """

    id: UUID
    #: The spelling that survives a "same": the fuller of the two. Stated on
    #: screen, not editable in v1.
    kept_name: str
    #: The other spelling, exactly as the school wrote it.
    other_name: str
    question: str


class SpellingAnswerRequest(CamelResponse):
    """The answer. Binary: they are one subject, or they are two."""

    same: bool


@router.get("/subjects/spelling-questions", response_model=list[SpellingQuestion])
async def spelling_questions(
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> list[SpellingQuestion]:
    """Every pair of spellings still waiting on an answer, listed together.

    Listed rather than shown one modal at a time, because a school whose file
    carried four abbreviations should answer four questions on one screen.
    """

    actor = await require_school_actor(session, principal, roles=ADMIN_ROLES)
    rows = list(
        await session.scalars(
            select(SubjectSpellingQuestion)
            .where(
                SubjectSpellingQuestion.school_id == _school_of(actor),
                SubjectSpellingQuestion.answer == SpellingAnswer.UNANSWERED,
            )
            .order_by(SubjectSpellingQuestion.created_at)
        )
    )
    kept = await _kept_names(session, rows)
    return [
        SpellingQuestion(
            id=row.id,
            kept_name=kept.get(row.kept_subject_id, row.other_label),
            other_name=row.other_label,
            question=(
                f"{kept.get(row.kept_subject_id, row.other_label)} and "
                f"{row.other_label} - same subject or different?"
            ),
        )
        for row in rows
    ]


@router.post(
    "/subjects/spelling-questions/{question_id}",
    response_model=list[SchoolSubjectResponse],
)
async def answer_spelling_question(
    question_id: UUID,
    payload: SpellingAnswerRequest,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> list[SchoolSubjectResponse]:
    """Settle one pair, and return the subjects it left behind.

    "Same" lets the fold stand: one subject, the fuller spelling surviving.
    "Different" splits the other spelling back out as the school's own row,
    keeping both labels exactly as the school wrote them. Nothing already
    recorded against the kept row moves, because records reference the row
    and not the words.
    """

    actor = await require_school_actor(session, principal, roles=ADMIN_ROLES)
    school_id = _school_of(actor)
    question = await session.get(SubjectSpellingQuestion, question_id)
    if question is None or question.school_id != school_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "question_not_found", "message": "No such question."},
        )
    if question.answer is not SpellingAnswer.UNANSWERED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "question_already_answered",
                "message": "Somebody has answered this already.",
            },
        )
    subjects = [question.kept_subject_id]
    question.answer = SpellingAnswer.SAME if payload.same else SpellingAnswer.DIFFERENT
    question.answered_at = datetime.now(UTC)
    if not payload.same:
        split = SchoolSubject(
            school_id=school_id,
            name=question.other_label,
            normalised_name=question.normalised_other,
            origin=SubjectOrigin.SCHOOL,
            # The school's own words, kept as the school's own words. This is
            # not a near-duplicate to be reviewed - they have just told us it
            # is a subject in its own right.
            review_state=SubjectReviewState.KEPT,
            created_by_user_id=actor.id,
        )
        session.add(split)
        await session.flush()
        question.split_subject_id = split.id
        subjects.append(split.id)
    await session.commit()
    rows = list(await session.scalars(select(SchoolSubject).where(SchoolSubject.id.in_(subjects))))
    names = await display_names(session, [row.id for row in rows])
    used = await _referenced(session, [row.id for row in rows])
    return [
        SchoolSubjectResponse(
            id=row.id,
            name=row.name,
            display_name=names.get(row.id, row.name),
            origin=row.origin,
            review_state=row.review_state,
            removable=row.id not in used,
        )
        for row in sorted(rows, key=lambda row: row.name)
    ]


async def _kept_names(
    session: DatabaseSession, rows: list[SubjectSpellingQuestion]
) -> dict[UUID, str]:
    """The surviving spelling of each pair, in one query rather than one each."""

    if not rows:
        return {}
    found = await session.execute(
        select(SchoolSubject.id, SchoolSubject.name).where(
            SchoolSubject.id.in_([row.kept_subject_id for row in rows])
        )
    )
    return dict(found.all())  # type: ignore[arg-type]


@router.get("/subjects/canonical", response_model=list[CanonicalSubjectResponse])
async def canonical_list(
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> list[CanonicalSubjectResponse]:
    """Nevo's list, for a picker. The same in every school."""

    await require_school_actor(session, principal)
    rows = await session.scalars(select(CanonicalSubject).order_by(CanonicalSubject.display_name))
    return [
        CanonicalSubjectResponse(id=row.id, slug=row.slug, display_name=row.display_name)
        for row in rows
    ]


@router.get("/subjects", response_model=list[SchoolSubjectResponse])
async def school_list(
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> list[SchoolSubjectResponse]:
    """This school's list: what it can put on a class or a teacher."""

    actor = await require_school_actor(session, principal)
    rows = list(
        await session.scalars(
            select(SchoolSubject)
            .where(SchoolSubject.school_id == actor.school_id)
            .order_by(SchoolSubject.name)
        )
    )
    names = await display_names(session, [row.id for row in rows])
    used = await _referenced(session, [row.id for row in rows])
    return [
        SchoolSubjectResponse(
            id=row.id,
            name=row.name,
            display_name=names.get(row.id, row.name),
            origin=row.origin,
            review_state=row.review_state,
            removable=row.id not in used,
        )
        for row in rows
    ]


@router.post(
    "/subjects",
    response_model=SchoolSubjectResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_subject(
    payload: AddSubjectRequest,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> SchoolSubjectResponse:
    """Put a subject on this school's list.

    A name matching one of Nevo's becomes that canonical subject for this
    school. Anything else becomes the school's own, pending review, and
    behaves identically everywhere else.
    """

    actor = await require_school_actor(session, principal, roles=ADMIN_ROLES)
    subject = await ensure(
        session,
        school_id=_school_of(actor),
        typed=payload.name,
        created_by_user_id=actor.id,
    )
    await session.commit()
    names = await display_names(session, [subject.id])
    return SchoolSubjectResponse(
        id=subject.id,
        name=subject.name,
        display_name=names.get(subject.id, subject.name),
        origin=subject.origin,
        review_state=subject.review_state,
        removable=True,
    )


@router.get("/subjects/resolve", response_model=list[ResolvePreview])
async def resolve_subjects(
    principal: PrincipalDependency,
    session: DatabaseSession,
    name: Annotated[list[str], Query(min_length=1, max_length=50)],
) -> list[ResolvePreview]:
    """What these typed strings would become. Writes nothing.

    The import confirmation step reads this so an administrator settles the
    unresolved ones before anything is saved. Saving an unresolved subject
    means a term of the same subject split three ways in every report, with no
    way to put it back together.
    """

    actor = await require_school_actor(session, principal, roles=ADMIN_ROLES)
    school_id = _school_of(actor)
    previews: list[ResolvePreview] = []
    for typed in name:
        found = await resolve(session, school_id=school_id, typed=typed)
        previews.append(
            ResolvePreview(
                typed=found.typed,
                resolved=found.resolved,
                display_name=found.display_name,
                school_subject_id=found.school_subject_id,
                origin=found.origin,
            )
        )
    return previews


@router.put("/teachers/{teacher_id}/subjects", response_model=list[SchoolSubjectResponse])
async def set_teacher_subjects(
    teacher_id: UUID,
    payload: list[SubjectName],
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> list[SchoolSubjectResponse]:
    """What this person teaches. Not where they teach it.

    Replaces the list rather than adding to it, for the same reason a class's
    does: a list somebody cannot remove from is not a list they control.
    Removing a subject a teacher is still assigned to is refused, because that
    would leave an assignment naming a subject its teacher does not hold.
    """

    actor = await require_school_actor(session, principal, roles=ADMIN_ROLES)
    school_id = _school_of(actor)
    teacher = await session.get(User, teacher_id)
    if teacher is None or teacher.school_id != school_id or teacher.role is not UserRole.TEACHER:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Teacher not found")

    wanted: set[UUID] = set()
    for typed in payload:
        subject = await ensure(
            session, school_id=school_id, typed=typed, created_by_user_id=actor.id
        )
        wanted.add(subject.id)
    held = {
        row[0]
        for row in await session.execute(
            select(TeacherSubject.school_subject_id).where(TeacherSubject.teacher_id == teacher_id)
        )
    }
    for subject_id in held - wanted:
        if await _assigned_with(session, teacher_id=teacher_id, school_subject_id=subject_id):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "subject_in_use_by_assignment",
                    "message": (
                        "This teacher is still assigned to a class for that subject. "
                        "Remove the assignment first."
                    ),
                },
            )
        await session.execute(
            delete(TeacherSubject).where(
                TeacherSubject.teacher_id == teacher_id,
                TeacherSubject.school_subject_id == subject_id,
            )
        )
    for subject_id in wanted - held:
        session.add(TeacherSubject(teacher_id=teacher_id, school_subject_id=subject_id))
    await session.commit()

    rows = list(
        await session.scalars(
            select(SchoolSubject)
            .join(TeacherSubject, TeacherSubject.school_subject_id == SchoolSubject.id)
            .where(TeacherSubject.teacher_id == teacher_id)
            .order_by(SchoolSubject.name)
        )
    )
    names = await display_names(session, [row.id for row in rows])
    return [
        SchoolSubjectResponse(
            id=row.id,
            name=row.name,
            display_name=names.get(row.id, row.name),
            origin=row.origin,
            review_state=row.review_state,
        )
        for row in rows
    ]


@router.get("/teachers/{teacher_id}/subjects", response_model=list[SchoolSubjectResponse])
async def get_teacher_subjects(
    teacher_id: UUID,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> list[SchoolSubjectResponse]:
    actor = await require_school_actor(session, principal)
    teacher = await session.get(User, teacher_id)
    if (
        teacher is None
        or teacher.school_id != actor.school_id
        or teacher.role is not UserRole.TEACHER
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Teacher not found")
    rows = list(
        await session.scalars(
            select(SchoolSubject)
            .join(TeacherSubject, TeacherSubject.school_subject_id == SchoolSubject.id)
            .where(TeacherSubject.teacher_id == teacher_id)
            .order_by(SchoolSubject.name)
        )
    )
    names = await display_names(session, [row.id for row in rows])
    return [
        SchoolSubjectResponse(
            id=row.id,
            name=row.name,
            display_name=names.get(row.id, row.name),
            origin=row.origin,
            review_state=row.review_state,
        )
        for row in rows
    ]


@router.post(
    "/teachers/{teacher_id}/subjects",
    response_model=list[SchoolSubjectResponse],
    status_code=status.HTTP_201_CREATED,
)
async def add_teacher_subject(
    teacher_id: UUID,
    payload: AddSubjectRequest,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> list[SchoolSubjectResponse]:
    """Append one subject without replacing the teacher's existing list."""
    actor = await require_school_actor(session, principal, roles=ADMIN_ROLES)
    teacher = await session.get(User, teacher_id)
    if (
        teacher is None
        or teacher.school_id != actor.school_id
        or teacher.role is not UserRole.TEACHER
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Teacher not found")
    subject = await ensure(
        session,
        school_id=_school_of(actor),
        typed=payload.name,
        created_by_user_id=actor.id,
    )
    existing = await session.scalar(
        select(TeacherSubject).where(
            TeacherSubject.teacher_id == teacher_id,
            TeacherSubject.school_subject_id == subject.id,
        )
    )
    if existing is None:
        session.add(TeacherSubject(teacher_id=teacher_id, school_subject_id=subject.id))
        await session.commit()
    return await get_teacher_subjects(teacher_id, principal, session)


async def _referenced(session: DatabaseSession, subject_ids: list[UUID]) -> set[UUID]:
    """Subjects something already points at, so a screen does not offer to remove them."""

    if not subject_ids:
        return set()
    used: set[UUID] = set()
    for table in (ClassSubject, TeacherSubject):
        rows = await session.execute(
            select(table.school_subject_id).where(table.school_subject_id.in_(subject_ids))
        )
        used.update(row[0] for row in rows)
    return used


async def _assigned_with(
    session: DatabaseSession, *, teacher_id: UUID, school_subject_id: UUID
) -> bool:
    from nevo.db.models.teacher_assignment import TeacherClassAssignment

    found = await session.scalar(
        select(TeacherClassAssignment.id).where(
            TeacherClassAssignment.teacher_id == teacher_id,
            TeacherClassAssignment.school_subject_id == school_subject_id,
            TeacherClassAssignment.removed_at.is_(None),
        )
    )
    return found is not None


def _school_of(user: User) -> UUID:
    if user.school_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "school_context_required",
                "message": "This action belongs to a school account.",
            },
        )
    return user.school_id


__all__ = ["normalise", "router"]
