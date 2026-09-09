import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nevo.access import accessible_classes, accessible_lessons, accessible_students
from nevo.ask_nevo.directory import PseudonymDirectory
from nevo.db.models.account import (
    Class,
    ConsentRecord,
    StudentClassEnrollment,
    User,
)
from nevo.db.models.attention_flag import AttentionFlag
from nevo.db.models.consent import ParentLink
from nevo.db.models.content import Lesson, LessonSegment
from nevo.db.models.frontend_support import Concept, LessonAssignment
from nevo.db.models.learner_profile import LearnerProfile
from nevo.db.models.mastery import StudentConceptMastery, StudentConceptScheduling
from nevo.db.models.signal_event import LessonSession
from nevo.domain.accounts.vocabulary import UserRole, UserStatus
from nevo.domain.ask_nevo.vocabulary import AskNevoRole
from nevo.domain.signal_events.vocabulary import LessonCompletionStatus

logger = logging.getLogger(__name__)

NOT_PERMITTED = {"error": "not_permitted", "detail": "That learner is not in your classes."}
NOT_FOUND = {"error": "not_found", "detail": "No record matched."}
MAX_ROWS = 20

STAFF = (AskNevoRole.TEACHER, AskNevoRole.ADMIN)
"""Roles that look at other people's learners."""

EVERYONE = (
    AskNevoRole.STUDENT,
    AskNevoRole.TEACHER,
    AskNevoRole.PARENT,
    AskNevoRole.ADMIN,
)


@dataclass(frozen=True, slots=True)
class ToolContext:
    """Everything a tool is allowed to act on behalf of."""

    session: AsyncSession
    actor: User
    directory: PseudonymDirectory
    role: AskNevoRole = AskNevoRole.TEACHER


TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "find_learners",
        "roles": STAFF,
        "description": (
            "Find learners the asking user teaches or administers. Use when a "
            "question names a learner, or to list who is in scope. Learners are "
            "identified by an opaque code such as Learner-A1B2C3; you will never "
            "see real names and must refer to learners only by that code."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "A learner code to match, or leave empty to list everyone "
                        "in scope."
                    ),
                }
            },
            "required": [],
        },
    },
    {
        "name": "get_learner_overview",
        "roles": STAFF,
        "description": (
            "Current picture for one learner: profile summary, recent sessions "
            "and open attention flags. Use before answering anything specific "
            "about how a learner is doing."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "learner": {"type": "string", "description": "Learner code, e.g. Learner-A1B2C3."}
            },
            "required": ["learner"],
        },
    },
    {
        "name": "list_classes",
        "roles": STAFF,
        "description": "Classes the asking user teaches or administers.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_class_overview",
        "roles": STAFF,
        "description": (
            "Roster size and recent activity for one class. Use for questions "
            "about how a class as a whole is doing."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"class_id": {"type": "string", "description": "Class UUID."}},
            "required": ["class_id"],
        },
    },
    {
        "name": "get_recent_flags",
        "roles": STAFF,
        "description": (
            "Attention flags raised recently, for one learner or across the "
            "asking user's classes. Use for 'who needs attention' questions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "learner": {"type": "string", "description": "Optional learner code."}
            },
            "required": [],
        },
    },
    {
        "name": "get_lesson_overview",
        "roles": (*STAFF, AskNevoRole.STUDENT),
        "description": "Structure and review state of one lesson.",
        "input_schema": {
            "type": "object",
            "properties": {"lesson_id": {"type": "string", "description": "Lesson UUID."}},
            "required": ["lesson_id"],
        },
    },
    {
        "name": "get_my_work",
        "roles": (AskNevoRole.STUDENT,),
        "description": (
            "What this learner has been set: lessons assigned to them, what is "
            "still to do, and anything with a due date. Use for 'what do I have "
            "to do', 'what is due', 'have I finished everything'."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_my_progress",
        "roles": (AskNevoRole.STUDENT,),
        "description": (
            "How this learner has been getting on lately: lessons finished, "
            "ideas they are confident with, and what they have been working on. "
            "Use for 'how am I doing', 'what have I learnt', 'am I improving'. "
            "Never report a score or a comparison with anyone else."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_my_revision",
        "roles": (AskNevoRole.STUDENT,),
        "description": (
            "Ideas this learner is due to go back over, soonest first. Use for "
            "'what should I revise', 'what should I practise', 'what have I "
            "forgotten'."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_lesson_content",
        "roles": (AskNevoRole.STUDENT, AskNevoRole.TEACHER, AskNevoRole.ADMIN),
        "description": (
            "The actual text of a lesson's segments, so a part of it can be "
            "explained again or differently. Use when a question is about "
            "something in the lesson rather than about a person."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "lesson_id": {"type": "string", "description": "Lesson UUID."},
                "segment_id": {
                    "type": "string",
                    "description": "Optional segment key, to fetch just that part.",
                },
            },
            "required": ["lesson_id"],
        },
    },
    {
        "name": "list_my_lessons",
        "roles": STAFF,
        "description": (
            "Lessons this teacher wrote, assigned, or teaches to a class. Use "
            "for 'what lessons do I have', 'what have I made', 'what am I "
            "teaching'."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_assignment_status",
        "roles": STAFF,
        "description": (
            "Who has finished a lesson and who has not started it. Use for "
            "'has everyone done the homework', 'who is behind', 'who has not "
            "started'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "lesson_id": {"type": "string", "description": "Lesson UUID."},
                "class_id": {"type": "string", "description": "Optional class UUID."},
            },
            "required": ["lesson_id"],
        },
    },
    {
        "name": "get_concept_mastery",
        "roles": STAFF,
        "description": (
            "Which ideas a learner or a class is confident with and which are "
            "still shaky, named as concepts rather than scores. Use for 'what "
            "is the class struggling with', 'what should I reteach', 'what "
            "does this learner need next'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "learner": {"type": "string", "description": "Optional learner code."},
                "class_id": {"type": "string", "description": "Optional class UUID."},
            },
            "required": [],
        },
    },
    {
        "name": "get_due_revision",
        "roles": STAFF,
        "description": (
            "Learners with ideas due for retrieval practice. Use for 'who needs "
            "to revise', 'what should we go back over'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "class_id": {"type": "string", "description": "Optional class UUID."},
            },
            "required": [],
        },
    },
    {
        "name": "get_consent_status",
        "roles": (AskNevoRole.ADMIN,),
        "description": (
            "Whether consent has been recorded for a learner, and how. Use for "
            "'has this learner's parent consented', 'who is missing consent'. "
            "Administrators only."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "learner": {"type": "string", "description": "Optional learner code."},
            },
            "required": [],
        },
    },
    {
        "name": "get_school_overview",
        "roles": (AskNevoRole.ADMIN,),
        "description": (
            "Counts across the whole school: active learners, teachers, "
            "classes, lessons. Use for 'how many learners do we have', 'how big "
            "is our roster'. Administrators only."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_my_children",
        "roles": (AskNevoRole.PARENT,),
        "description": (
            "The children this parent is linked to. Use before answering "
            "anything about a child, to find out who they are asking about."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_child_progress",
        "roles": (AskNevoRole.PARENT,),
        "description": (
            "How one of this parent's own children is getting on, in plain "
            "language. Never a score, a percentage, a label, or a comparison "
            "with another child."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "learner": {"type": "string", "description": "Learner code."},
            },
            "required": ["learner"],
        },
    },
]


async def execute_tool(ctx: ToolContext, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Run one tool call.

    Every identifier here came from the model and is untrusted. Nothing is
    looked up directly by it: each tool resolves against the actor's own
    accessible set first, so an argument naming something out of reach returns
    a refusal rather than data.

    A refusal is a value, not an exception - the model needs to be able to tell
    the user it cannot see something.
    """
    handler = _HANDLERS.get(name)
    if handler is None:
        return {"error": "unknown_tool", "detail": f"No tool named {name}."}
    if not permits(ctx.role, name):
        # The offered list is a convenience; this is the boundary. A model that
        # invents a tool name it was not given still cannot reach past its
        # asker's role.
        return {"error": "not_permitted", "detail": "That is not available to you."}
    try:
        return await handler(ctx, arguments)
    except (ValueError, TypeError, KeyError):
        return {"error": "invalid_arguments", "detail": "Could not read those arguments."}
    except Exception:
        # One tool falling over must not take the answer with it. The model
        # gets a refusal it can talk about, and the reason goes to the log
        # rather than to the person asking.
        logger.exception("Ask Nevo tool %s failed", name)
        return {"error": "unavailable", "detail": "That could not be looked up just now."}


async def _find_learners(ctx: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    query = str(arguments.get("query") or "").strip().casefold()
    entries = ctx.directory.entries
    if query:
        entries = tuple(entry for entry in entries if query in entry.pseudonym.casefold())
    return {
        "learners": [{"learner": entry.pseudonym} for entry in entries[:MAX_ROWS]],
        "total": len(entries),
    }


async def _get_learner_overview(ctx: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    entry = ctx.directory.resolve(str(arguments.get("learner") or ""))
    if entry is None:
        return NOT_PERMITTED
    session = ctx.session
    profile = await session.scalar(
        select(LearnerProfile).where(LearnerProfile.learner_id == entry.student_id)
    )
    sessions = (
        await session.scalars(
            select(LessonSession)
            .where(LessonSession.student_id == entry.student_id)
            .order_by(LessonSession.started_at.desc())
            .limit(5)
        )
    ).all()
    flags = (
        await session.scalars(
            select(AttentionFlag)
            .where(
                AttentionFlag.student_id == entry.student_id,
                AttentionFlag.acknowledged_at.is_(None),
            )
            .order_by(AttentionFlag.generated_at.desc())
            .limit(5)
        )
    ).all()
    # Only things a teacher can act on. Internals - profile version numbers,
    # observed-event counts, evaluation timestamps - are deliberately absent:
    # the model can only narrate what it is handed, and a teacher told about a
    # "profile version" learns nothing and starts doubting the data.
    finished = sum(
        1
        for item in sessions
        if item.completion_status is LessonCompletionStatus.COMPLETED
    )
    return {
        "learner": entry.pseudonym,
        "has_learning_profile": profile is not None,
        "profile_note": (
            "Nevo has watched enough lessons to build a picture."
            if profile is not None
            else "Not enough lessons yet for Nevo to build a picture."
        ),
        "sessions_seen": len(sessions),
        "sessions_finished": finished,
        "sessions_left_unfinished": len(sessions) - finished,
        "recent_sessions": [
            {
                "date": _date(item.started_at),
                "outcome": _session_outcome(item.completion_status),
                "breaks_taken": item.break_count,
            }
            for item in sessions
        ],
        "open_flags": [
            {
                "type": item.flag_type.value,
                "description": item.description,
                "raised": _date(item.generated_at),
            }
            for item in flags
        ],
    }


async def _list_classes(ctx: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    classes = await accessible_classes(ctx.session, ctx.actor)
    return {
        "classes": [
            {"class_id": str(item.id), "name": item.name, "year_group": item.year_group}
            for item in classes[:MAX_ROWS]
        ]
    }


async def _get_class_overview(ctx: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    class_id = _uuid(arguments.get("class_id"))
    if class_id is None:
        return NOT_FOUND
    # Derive from the actor's own classes rather than fetching then checking.
    allowed = {item.id: item for item in await accessible_classes(ctx.session, ctx.actor)}
    school_class: Class | None = allowed.get(class_id)
    if school_class is None:
        return NOT_PERMITTED
    roster = (
        await ctx.session.scalars(
            select(StudentClassEnrollment.student_id).where(
                StudentClassEnrollment.class_id == class_id
            )
        )
    ).all()
    learners = [
        pseudonym
        for pseudonym in (ctx.directory.pseudonym_for(student_id) for student_id in roster)
        if pseudonym
    ]
    open_flags = await ctx.session.scalar(
        select(func.count(AttentionFlag.id)).where(
            AttentionFlag.student_id.in_(roster),
            AttentionFlag.acknowledged_at.is_(None),
        )
    )
    return {
        "class_id": str(school_class.id),
        "name": school_class.name,
        "learner_count": len(roster),
        "learners": learners[:MAX_ROWS],
        "open_flag_count": int(open_flags or 0),
    }


async def _get_recent_flags(ctx: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    raw = str(arguments.get("learner") or "").strip()
    if raw:
        entry = ctx.directory.resolve(raw)
        if entry is None:
            return NOT_PERMITTED
        student_ids = [entry.student_id]
    else:
        student_ids = [item.student_id for item in ctx.directory.entries]
    if not student_ids:
        return {"flags": []}
    flags = (
        await ctx.session.scalars(
            select(AttentionFlag)
            .where(
                AttentionFlag.student_id.in_(student_ids),
                AttentionFlag.acknowledged_at.is_(None),
            )
            .order_by(AttentionFlag.generated_at.desc())
            .limit(MAX_ROWS)
        )
    ).all()
    return {
        "flags": [
            {
                "learner": ctx.directory.pseudonym_for(item.student_id),
                "type": item.flag_type.value,
                "description": item.description,
                "generated_at": _iso(item.generated_at),
            }
            for item in flags
        ]
    }


async def _get_lesson_overview(ctx: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    lesson_id = _uuid(arguments.get("lesson_id"))
    if lesson_id is None:
        return NOT_FOUND
    lesson = await ctx.session.get(Lesson, lesson_id)
    if lesson is None or lesson.school_id != ctx.actor.school_id:
        return NOT_PERMITTED
    segments = (
        await ctx.session.scalars(
            select(LessonSegment)
            .where(LessonSegment.lesson_id == lesson_id)
            .order_by(LessonSegment.sequence_order)
            .limit(MAX_ROWS)
        )
    ).all()
    return {
        "lesson_id": str(lesson.id),
        "title": lesson.title,
        "subject": lesson.subject,
        "estimated_minutes": lesson.estimated_minutes,
        "segment_count": lesson.segment_count,
        "needs_review_count": lesson.review_segment_count,
        "segments": [
            {
                "title": item.title,
                "content_type": item.content_type.value,
                "estimated_minutes": item.estimated_minutes,
                "needs_review": item.needs_review,
            }
            for item in segments
        ],
    }


async def _get_my_work(ctx: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    del arguments
    rows = (
        await ctx.session.execute(
            select(LessonAssignment, Lesson.title)
            .join(Lesson, Lesson.id == LessonAssignment.lesson_id)
            .where(
                LessonAssignment.student_id == ctx.actor.id,
                LessonAssignment.status != "cancelled",
            )
            .order_by(LessonAssignment.due_at.is_(None), LessonAssignment.due_at)
            .limit(MAX_ROWS)
        )
    ).all()
    return {
        "work": [
            {
                "lesson_id": str(assignment.lesson_id),
                "title": title,
                "status": assignment.status,
                "due": assignment.due_at.date().isoformat() if assignment.due_at else None,
            }
            for assignment, title in rows
        ],
        "still_to_do": sum(1 for item, _ in rows if item.status != "completed"),
    }


async def _get_my_progress(ctx: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    del arguments
    finished = int(
        await ctx.session.scalar(
            select(func.count(LessonSession.id)).where(
                LessonSession.student_id == ctx.actor.id,
                LessonSession.completion_status == LessonCompletionStatus.COMPLETED,
            )
        )
        or 0
    )
    started = int(
        await ctx.session.scalar(
            select(func.count(LessonSession.id)).where(
                LessonSession.student_id == ctx.actor.id
            )
        )
        or 0
    )
    confident = list(
        await ctx.session.scalars(
            select(Concept.name)
            .join(
                StudentConceptMastery,
                StudentConceptMastery.concept_id == Concept.id,
            )
            .where(
                StudentConceptMastery.student_id == ctx.actor.id,
                StudentConceptMastery.mastery_probability_concept >= 0.7,
            )
            .order_by(StudentConceptMastery.last_updated.desc())
            .limit(MAX_ROWS)
        )
    )
    # Counts of a learner's own work, which they may see. No score, no rank,
    # and nothing about anybody else.
    return {
        "lessons_finished": finished,
        "lessons_started": started,
        "ideas_confident_with": confident,
    }


async def _get_my_revision(ctx: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    del arguments
    rows = (
        await ctx.session.execute(
            select(Concept.name, StudentConceptScheduling.next_review_due)
            .join(
                StudentConceptScheduling,
                StudentConceptScheduling.concept_id == Concept.id,
            )
            .where(StudentConceptScheduling.student_id == ctx.actor.id)
            .order_by(StudentConceptScheduling.next_review_due)
            .limit(MAX_ROWS)
        )
    ).all()
    return {
        "to_revise": [
            {"idea": name, "due": due.date().isoformat() if due else None}
            for name, due in rows
        ]
    }


async def _get_lesson_content(ctx: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    lesson_id = _uuid(arguments.get("lesson_id"))
    if lesson_id is None:
        return NOT_FOUND
    lessons = await accessible_lessons(ctx.session, ctx.actor)
    if not any(item.id == lesson_id for item in lessons):
        return {"error": "not_permitted", "detail": "That lesson is not one of yours."}
    query = select(LessonSegment).where(LessonSegment.lesson_id == lesson_id)
    segment_key = str(arguments.get("segment_id") or "").strip()
    if segment_key:
        query = query.where(LessonSegment.segment_key == segment_key)
    segments = list(
        await ctx.session.scalars(query.order_by(LessonSegment.sequence_order).limit(MAX_ROWS))
    )
    if not segments:
        return NOT_FOUND
    return {
        "segments": [
            {
                "segment_id": item.segment_key,
                "title": item.title,
                "body": item.body[:1500],
                "available_ways_to_learn": item.available_modalities,
            }
            for item in segments
        ]
    }


async def _list_my_lessons(ctx: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    del arguments
    lessons = await accessible_lessons(ctx.session, ctx.actor)
    return {
        "lessons": [
            {
                "lesson_id": str(item.id),
                "title": item.title,
                "subject": item.subject,
                "segments": item.segment_count,
                "needs_review": item.review_segment_count,
            }
            for item in lessons[:MAX_ROWS]
        ],
        "total": len(lessons),
    }


async def _get_assignment_status(ctx: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    lesson_id = _uuid(arguments.get("lesson_id"))
    if lesson_id is None:
        return NOT_FOUND
    lessons = await accessible_lessons(ctx.session, ctx.actor)
    if not any(item.id == lesson_id for item in lessons):
        return {"error": "not_permitted", "detail": "That lesson is not one of yours."}
    reachable = {student.id for student in await accessible_students(ctx.session, ctx.actor)}
    query = select(LessonAssignment).where(
        LessonAssignment.lesson_id == lesson_id,
        LessonAssignment.status != "cancelled",
    )
    class_id = _uuid(arguments.get("class_id"))
    if class_id is not None:
        query = query.where(LessonAssignment.class_id == class_id)
    rows = [
        item
        for item in await ctx.session.scalars(query)
        if item.student_id in reachable
    ]
    done: list[str] = []
    not_started: list[str] = []
    for item in rows:
        code = ctx.directory.pseudonym_for(item.student_id)
        if code is None:
            continue
        (done if item.status == "completed" else not_started).append(code)
    return {
        "assigned": len(rows),
        "finished": done[:MAX_ROWS],
        "not_finished": not_started[:MAX_ROWS],
    }


async def _get_concept_mastery(ctx: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    student_ids = await _requested_learner_ids(ctx, arguments)
    if student_ids is None:
        return NOT_PERMITTED
    rows = (
        await ctx.session.execute(
            select(
                Concept.name,
                func.avg(StudentConceptMastery.mastery_probability_concept),
                func.count(StudentConceptMastery.id),
            )
            .join(
                StudentConceptMastery,
                StudentConceptMastery.concept_id == Concept.id,
            )
            .where(StudentConceptMastery.student_id.in_(student_ids))
            .group_by(Concept.name)
            .order_by(func.avg(StudentConceptMastery.mastery_probability_concept))
            .limit(MAX_ROWS)
        )
    ).all()
    # Bucketed rather than reported as a number: a probability is not
    # something to read out to a teacher as if it were a mark.
    return {
        "learners_considered": len(student_ids),
        "ideas": [
            {
                "idea": name,
                "standing": (
                    "still shaky"
                    if float(average or 0) < 0.5
                    else "coming along"
                    if float(average or 0) < 0.7
                    else "confident"
                ),
                "learners_practising": int(count),
            }
            for name, average, count in rows
        ],
    }


async def _get_due_revision(ctx: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    student_ids = await _requested_learner_ids(ctx, arguments)
    if student_ids is None:
        return NOT_PERMITTED
    rows = (
        await ctx.session.execute(
            select(
                StudentConceptScheduling.student_id,
                func.count(StudentConceptScheduling.id),
            )
            .where(
                StudentConceptScheduling.student_id.in_(student_ids),
                StudentConceptScheduling.next_review_due <= func.now(),
            )
            .group_by(StudentConceptScheduling.student_id)
            .order_by(func.count(StudentConceptScheduling.id).desc())
            .limit(MAX_ROWS)
        )
    ).all()
    return {
        "due_now": [
            {"learner": code, "ideas_due": int(count)}
            for student_id, count in rows
            if (code := ctx.directory.pseudonym_for(student_id)) is not None
        ]
    }


async def _get_consent_status(ctx: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    student_ids = await _requested_learner_ids(ctx, arguments)
    if student_ids is None:
        return NOT_PERMITTED
    rows = (
        await ctx.session.execute(
            select(ConsentRecord.subject_user_id, ConsentRecord.status)
            .where(ConsentRecord.subject_user_id.in_(student_ids))
            .limit(MAX_ROWS * 3)
        )
    ).all()
    recorded = {student_id: status.value for student_id, status in rows}
    return {
        "consent": [
            {"learner": code, "status": recorded.get(student_id, "not_sent")}
            for student_id in student_ids[:MAX_ROWS]
            if (code := ctx.directory.pseudonym_for(student_id)) is not None
        ]
    }


async def _get_school_overview(ctx: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    del arguments
    if ctx.actor.school_id is None:
        return NOT_FOUND

    async def count(role: UserRole) -> int:
        return int(
            await ctx.session.scalar(
                select(func.count(User.id)).where(
                    User.school_id == ctx.actor.school_id,
                    User.role == role,
                    User.status == UserStatus.ACTIVE,
                )
            )
            or 0
        )

    return {
        "active_learners": await count(UserRole.STUDENT),
        "teachers": await count(UserRole.TEACHER),
        "classes": int(
            await ctx.session.scalar(
                select(func.count(Class.id)).where(
                    Class.school_id == ctx.actor.school_id,
                    Class.archived_at.is_(None),
                )
            )
            or 0
        ),
        "lessons": int(
            await ctx.session.scalar(
                select(func.count(Lesson.id)).where(
                    Lesson.school_id == ctx.actor.school_id
                )
            )
            or 0
        ),
    }


async def _get_my_children(ctx: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    del arguments
    rows = (
        await ctx.session.execute(
            select(ParentLink.student_id, User.status)
            .join(User, User.id == ParentLink.student_id)
            .where(ParentLink.parent_id == ctx.actor.id)
        )
    ).all()
    return {
        "children": [
            {"learner": code, "status": status.value}
            for student_id, status in rows
            if (code := ctx.directory.pseudonym_for(student_id)) is not None
        ]
    }


async def _get_child_progress(ctx: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    entry = ctx.directory.resolve(str(arguments.get("learner") or ""))
    if entry is None:
        return {"error": "not_permitted", "detail": "That is not one of your children."}
    student_id = entry.student_id
    linked = await ctx.session.scalar(
        select(ParentLink.id).where(
            ParentLink.parent_id == ctx.actor.id,
            ParentLink.student_id == student_id,
        )
    )
    if linked is None:
        return {"error": "not_permitted", "detail": "That is not one of your children."}
    finished = int(
        await ctx.session.scalar(
            select(func.count(LessonSession.id)).where(
                LessonSession.student_id == student_id,
                LessonSession.completion_status == LessonCompletionStatus.COMPLETED,
            )
        )
        or 0
    )
    subjects = list(
        await ctx.session.scalars(
            select(Lesson.subject)
            .join(LessonSession, LessonSession.lesson_id == Lesson.id)
            .where(LessonSession.student_id == student_id, Lesson.subject.is_not(None))
            .distinct()
            .limit(MAX_ROWS)
        )
    )
    # No scores, no labels, no other children. A parent gets what their child
    # has been doing, described.
    return {
        "lessons_finished": finished,
        "subjects_worked_on": subjects,
        "note": (
            "Describe this in plain language. Do not give a score, a level, a "
            "label, or any comparison with another child."
        ),
    }


async def _requested_learner_ids(
    ctx: ToolContext,
    arguments: dict[str, Any],
) -> list[UUID] | None:
    """Resolve a learner code or a class to ids this actor may actually see.

    Returns None when the request names something out of reach, so the caller
    answers with a refusal rather than a smaller set that hides the reason.
    """
    code = str(arguments.get("learner") or "").strip()
    if code:
        entry = ctx.directory.resolve(code)
        return None if entry is None else [entry.student_id]
    reachable = await accessible_students(ctx.session, ctx.actor)
    class_id = _uuid(arguments.get("class_id"))
    if class_id is None:
        return [student.id for student in reachable]
    classes = await accessible_classes(ctx.session, ctx.actor)
    if not any(item.id == class_id for item in classes):
        return None
    enrolled = set(
        await ctx.session.scalars(
            select(StudentClassEnrollment.student_id).where(
                StudentClassEnrollment.class_id == class_id
            )
        )
    )
    return [student.id for student in reachable if student.id in enrolled]


_HANDLERS = {
    "find_learners": _find_learners,
    "get_learner_overview": _get_learner_overview,
    "list_classes": _list_classes,
    "get_class_overview": _get_class_overview,
    "get_recent_flags": _get_recent_flags,
    "get_lesson_overview": _get_lesson_overview,
    "get_my_work": _get_my_work,
    "get_my_progress": _get_my_progress,
    "get_my_revision": _get_my_revision,
    "get_lesson_content": _get_lesson_content,
    "list_my_lessons": _list_my_lessons,
    "get_assignment_status": _get_assignment_status,
    "get_concept_mastery": _get_concept_mastery,
    "get_due_revision": _get_due_revision,
    "get_consent_status": _get_consent_status,
    "get_school_overview": _get_school_overview,
    "get_my_children": _get_my_children,
    "get_child_progress": _get_child_progress,
}


def schemas_for(role: AskNevoRole) -> tuple[dict[str, Any], ...]:
    """The tools this asker may use, with the gating stripped off.

    Every role used to be handed the same six, so a learner was offered
    get_class_overview and get_recent_flags - tools that can only ever refuse
    for them. Offering a tool that cannot work is a worse answer than not
    offering it.
    """
    return tuple(
        {key: value for key, value in schema.items() if key != "roles"}
        for schema in TOOL_SCHEMAS
        if role in schema["roles"]
    )


def permits(role: AskNevoRole, name: str) -> bool:
    """Whether this asker may run this tool at all.

    Checked at execution as well as at selection: the list offered to the
    model is a convenience, not the boundary.
    """
    for schema in TOOL_SCHEMAS:
        if schema["name"] == name:
            return role in schema["roles"]
    return False


def _uuid(value: Any) -> UUID | None:
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None and hasattr(value, "isoformat") else None


def _date(value: Any) -> str | None:
    """A date a teacher would say out loud, not a timestamp."""
    return value.strftime("%-d %B") if value is not None and hasattr(value, "strftime") else None


def _session_outcome(status: LessonCompletionStatus) -> str:
    """Plain words for what happened, rather than an internal status token."""
    return {
        LessonCompletionStatus.COMPLETED: "finished",
        LessonCompletionStatus.IN_PROGRESS: "still open",
        LessonCompletionStatus.EXITED: "left early",
    }.get(status, "unknown")
