from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nevo.ask_nevo.directory import PseudonymDirectory, accessible_classes
from nevo.db.models.account import Class, StudentClassEnrollment, User
from nevo.db.models.attention_flag import AttentionFlag
from nevo.db.models.content import Lesson, LessonSegment
from nevo.db.models.learner_profile import LearnerProfile
from nevo.db.models.signal_event import LessonSession

NOT_PERMITTED = {"error": "not_permitted", "detail": "That learner is not in your classes."}
NOT_FOUND = {"error": "not_found", "detail": "No record matched."}
MAX_ROWS = 20


@dataclass(frozen=True, slots=True)
class ToolContext:
    """Everything a tool is allowed to act on behalf of."""

    session: AsyncSession
    actor: User
    directory: PseudonymDirectory


TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "find_learners",
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
        "description": "Classes the asking user teaches or administers.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_class_overview",
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
        "description": "Structure and review state of one lesson.",
        "input_schema": {
            "type": "object",
            "properties": {"lesson_id": {"type": "string", "description": "Lesson UUID."}},
            "required": ["lesson_id"],
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
    try:
        return await handler(ctx, arguments)
    except (ValueError, TypeError, KeyError):
        return {"error": "invalid_arguments", "detail": "Could not read those arguments."}


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
    return {
        "learner": entry.pseudonym,
        "profile": {
            "version": profile.version if profile else None,
            "observed_events": profile.observed_event_count if profile else 0,
            "last_evaluated_at": _iso(getattr(profile, "last_evaluated_at", None)),
        },
        "recent_sessions": [
            {
                "started_at": _iso(item.started_at),
                "completion_status": item.completion_status.value,
                "break_count": item.break_count,
            }
            for item in sessions
        ],
        "open_flags": [
            {
                "type": item.flag_type.value,
                "description": item.description,
                "generated_at": _iso(item.generated_at),
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


_HANDLERS = {
    "find_learners": _find_learners,
    "get_learner_overview": _get_learner_overview,
    "list_classes": _list_classes,
    "get_class_overview": _get_class_overview,
    "get_recent_flags": _get_recent_flags,
    "get_lesson_overview": _get_lesson_overview,
}


def _uuid(value: Any) -> UUID | None:
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None and hasattr(value, "isoformat") else None
