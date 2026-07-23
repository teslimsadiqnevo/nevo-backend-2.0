from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nevo.ask_nevo.entities import AskNevoContext, AskNevoRequest
from nevo.db.models.account import Class, User
from nevo.db.models.ask_nevo import AskNevoInteraction
from nevo.db.models.attention_flag import AttentionFlag, Escalation
from nevo.db.models.learner_profile import LearnerProfile
from nevo.db.models.signal_event import LessonSession
from nevo.db.models.teacher_assignment import TeacherClassAssignment
from nevo.domain.ask_nevo.vocabulary import AskNevoQuestionCategory


class SqlAlchemyAskNevoRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def build_context(
        self,
        *,
        actor_user_id: UUID,
        request: AskNevoRequest,
    ) -> AskNevoContext:
        async with self._sessions() as session:
            actor = await session.get(User, actor_user_id)
            payload: dict[str, object] = {
                "role": request.role.value,
                "current_page": request.current_page,
                "context_ids": _context_ids_payload(request),
                "actor": _user_payload(actor),
            }
            student_id = request.context_ids.student_id
            if student_id is not None:
                student = await session.get(User, student_id)
                profile = await session.scalar(
                    select(LearnerProfile).where(
                        LearnerProfile.learner_id == student_id
                    )
                )
                flags = (
                    await session.scalars(
                        select(AttentionFlag)
                        .where(AttentionFlag.student_id == student_id)
                        .order_by(AttentionFlag.generated_at.desc())
                        .limit(5)
                    )
                ).all()
                sessions = (
                    await session.scalars(
                        select(LessonSession)
                        .where(LessonSession.student_id == student_id)
                        .order_by(LessonSession.started_at.desc())
                        .limit(5)
                    )
                ).all()
                escalations = (
                    await session.scalars(
                        select(Escalation)
                        .where(Escalation.student_id == student_id)
                        .order_by(Escalation.generated_at.desc())
                        .limit(3)
                    )
                ).all()
                payload["student"] = _user_payload(student)
                payload["learner_profile"] = _profile_payload(profile)
                payload["recent_flags"] = [
                    {
                        "flag_type": flag.flag_type.value,
                        "description": flag.description,
                        "generated_at": flag.generated_at,
                    }
                    for flag in flags
                ]
                payload["recent_sessions"] = [
                    {
                        "id": str(item.id),
                        "lesson_id": str(item.lesson_id),
                        "started_at": item.started_at,
                        "completion_status": item.completion_status.value,
                        "break_count": item.break_count,
                    }
                    for item in sessions
                ]
                payload["recent_escalations"] = [
                    {
                        "teacher_id": str(item.teacher_id),
                        "teacher_note": item.teacher_note,
                        "generated_at": item.generated_at,
                    }
                    for item in escalations
                ]
            if request.context_ids.class_id is not None:
                school_class = await session.get(Class, request.context_ids.class_id)
                assignments = (
                    await session.scalars(
                        select(TeacherClassAssignment).where(
                            TeacherClassAssignment.class_id
                            == request.context_ids.class_id,
                            TeacherClassAssignment.removed_at.is_(None),
                        )
                    )
                ).all()
                payload["class"] = {
                    "id": str(school_class.id) if school_class else None,
                    "name": school_class.name if school_class else None,
                    "teacher_ids": [str(item.teacher_id) for item in assignments],
                }
            if request.context_ids.lesson_id is not None:
                payload["lesson"] = {
                    "id": str(request.context_ids.lesson_id),
                    "segment_id": request.context_ids.segment_id,
                    "note": "Lesson body is supplied by frontend/parser when available.",
                }
            return AskNevoContext(payload=payload, student_id_for_gateway=student_id)

    async def log_interaction(
        self,
        *,
        actor_user_id: UUID,
        request: AskNevoRequest,
        category: AskNevoQuestionCategory,
        ai_gateway_call_id: UUID,
    ) -> UUID:
        interaction_id = uuid4()
        async with self._sessions.begin() as session:
            session.add(
                AskNevoInteraction(
                    id=interaction_id,
                    actor_user_id=actor_user_id,
                    role=request.role,
                    current_page=request.current_page,
                    context_ids=_context_ids_payload(request),
                    question_category=category,
                    ai_gateway_call_id=ai_gateway_call_id,
                )
            )
        return interaction_id

    async def record_helpfulness(
        self,
        *,
        interaction_id: UUID,
        helpful: bool,
    ) -> None:
        async with self._sessions.begin() as session:
            await session.execute(
                update(AskNevoInteraction)
                .where(AskNevoInteraction.id == interaction_id)
                .values(response_helpful=helpful)
            )


def _context_ids_payload(request: AskNevoRequest) -> dict[str, str | None]:
    ids = request.context_ids
    return {
        "studentId": str(ids.student_id) if ids.student_id else None,
        "classId": str(ids.class_id) if ids.class_id else None,
        "lessonId": str(ids.lesson_id) if ids.lesson_id else None,
        "segmentId": ids.segment_id,
        "threadId": str(ids.thread_id) if ids.thread_id else None,
    }


def _user_payload(user: User | None) -> dict[str, object | None]:
    if user is None:
        return {}
    return {
        "id": str(user.id),
        "role": user.role.value,
        "first_name": user.first_name,
        "last_name": user.last_name,
    }


def _profile_payload(profile: LearnerProfile | None) -> dict[str, object | None]:
    if profile is None:
        return {"status": "not_observed_yet"}
    return {
        "visual_spatial_preference": profile.visual_spatial_preference.value
        if profile.visual_spatial_preference
        else None,
        "auditory_preference": profile.auditory_preference.value
        if profile.auditory_preference
        else None,
        "reading_writing_preference": profile.reading_writing_preference.value
        if profile.reading_writing_preference
        else None,
        "interactive_kinesthetic_preference": (
            profile.interactive_kinesthetic_preference.value
            if profile.interactive_kinesthetic_preference
            else None
        ),
        "working_memory_capacity": profile.working_memory_capacity,
        "attention_span": profile.attention_span,
    }
