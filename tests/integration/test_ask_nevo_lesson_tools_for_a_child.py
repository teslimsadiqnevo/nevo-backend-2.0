"""S11: Ask Nevo's lesson tools tell a child only about their own, open lessons.

get_lesson_overview checked the school alone, so a child could ask about any
lesson in it, and it returned review state. Neither tool dropped sections the
safety check held. A withdrawn assignment (status cancelled) must drop out too.
"""

import asyncio
from uuid import uuid4

import pytest

from tests.integration.test_me_identity import URL

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not URL, reason="Disposable database required"),
]


def _seed(sessions):
    from nevo.db.models.account import School, User
    from nevo.db.models.content import ContentParseRun, Lesson, LessonSegment
    from nevo.db.models.frontend_support import LessonAssignment

    async def run():
        async with sessions.begin() as session:
            school = School(
                name="Test School", school_code=uuid4().hex[:4].upper(),
                school_url_slug=f"test-{uuid4().hex[:8]}",
            )
            session.add(school)
            await session.flush()
            teacher = User(
                school_id=school.id, role="teacher", auth_method="email_password",
                status="active", email=f"t-{uuid4().hex[:8]}@nevolearning-tests.com",
            )
            child = User(
                school_id=school.id, role="student", auth_method="pin", status="active",
                login_identifier=f"NV-{uuid4().hex[:6]}",
            )
            session.add_all([teacher, child])
            await session.flush()
            lessons = {}
            for key in ("assigned", "unassigned", "withdrawn"):
                lesson = Lesson(
                    school_id=school.id, created_by_user_id=teacher.id, title=key,
                    source_type="pdf", status="completed", review_segment_count=1,
                )
                session.add(lesson)
                await session.flush()
                run_row = ContentParseRun(
                    lesson_id=lesson.id, requested_by_user_id=teacher.id, source_type="pdf"
                )
                session.add(run_row)
                await session.flush()
                for order, reasons in ((1, []), (2, ["safety_hold"])):
                    session.add(
                        LessonSegment(
                            lesson_id=lesson.id, parse_run_id=run_row.id,
                            segment_key=f"s{order}", content_type="explanatory_text",
                            sequence_order=order, title=f"part {order}",
                            body=f"body {order}", available_modalities=["text"],
                            review_reasons=reasons, needs_review=bool(reasons),
                        )
                    )
                lessons[key] = lesson.id
            session.add(
                LessonAssignment(
                    lesson_id=lessons["assigned"], student_id=child.id, teacher_id=teacher.id
                )
            )
            session.add(
                LessonAssignment(
                    lesson_id=lessons["withdrawn"], student_id=child.id,
                    teacher_id=teacher.id, status="cancelled",
                    cancellation_reason="wrong_content", recall_withdrawn=True,
                )
            )
            return child.id, teacher.id, lessons

    return asyncio.run(run())


def _call(sessions, actor_id, tool, arguments):
    from nevo.ask_nevo.tools import ToolContext, execute_tool
    from nevo.db.models.account import User

    async def run():
        async with sessions() as session:
            actor = await session.get(User, actor_id)
            ctx = ToolContext(session=session, actor=actor, directory=None)
            return await execute_tool(ctx, tool, arguments)

    return asyncio.run(run())


def test_a_child_is_told_only_about_their_own_lesson(me):
    _, _, sessions = me
    child, _, lessons = _seed(sessions)

    own = _call(sessions, child, "get_lesson_overview", {"lesson_id": str(lessons["assigned"])})
    other = _call(sessions, child, "get_lesson_overview", {"lesson_id": str(lessons["unassigned"])})
    gone = _call(sessions, child, "get_lesson_overview", {"lesson_id": str(lessons["withdrawn"])})

    assert own["title"] == "assigned"
    assert other.get("error") == "not_permitted"
    assert gone.get("error") == "not_permitted"


def test_a_child_sees_no_review_state_and_no_held_section(me):
    _, _, sessions = me
    child, _, lessons = _seed(sessions)

    assigned = {"lesson_id": str(lessons["assigned"])}
    overview = _call(sessions, child, "get_lesson_overview", assigned)
    content = _call(sessions, child, "get_lesson_content", assigned)

    assert "needs_review_count" not in overview
    assert all("needs_review" not in item for item in overview["segments"])
    assert [item["title"] for item in overview["segments"]] == ["part 1"]
    assert [item["title"] for item in content["segments"]] == ["part 1"]


def test_a_withdrawn_lesson_cannot_be_read_back(me):
    _, _, sessions = me
    child, _, lessons = _seed(sessions)

    content = _call(sessions, child, "get_lesson_content", {"lesson_id": str(lessons["withdrawn"])})

    assert content.get("error") == "not_permitted"


def test_a_teacher_still_sees_the_whole_lesson_and_its_review_state(me):
    _, _, sessions = me
    _, teacher, lessons = _seed(sessions)

    overview = _call(
        sessions, teacher, "get_lesson_overview", {"lesson_id": str(lessons["unassigned"])}
    )

    assert overview["needs_review_count"] == 1
    assert len(overview["segments"]) == 2
