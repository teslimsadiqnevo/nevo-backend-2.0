"""S21: the mastery read for staff, per learner and per year group, on a real database."""

import asyncio
import uuid

import httpx
import pytest
from fastapi import FastAPI

from tests.integration.test_me_identity import URL

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not URL, reason="Disposable database required"),
]


def _get(sessions, path, user_id, role):
    from nevo.api.auth import authenticated_principal
    from nevo.api.dependencies import database_session
    from nevo.api.mastery_read import router
    from nevo.auth.entities import AuthPrincipal

    app = FastAPI()
    app.include_router(router)

    async def db():
        async with sessions() as session:
            yield session

    app.dependency_overrides[database_session] = db
    app.dependency_overrides[authenticated_principal] = lambda: AuthPrincipal(
        user_id=user_id, role=role, session_id=uuid.uuid4()
    )

    async def go():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://t"
        ) as client:
            return await client.get(path)

    return asyncio.run(go())


def _numbers(value):
    if isinstance(value, bool):
        return []
    if isinstance(value, int | float):
        return [value]
    if isinstance(value, dict):
        return [n for item in value.values() for n in _numbers(item)]
    if isinstance(value, list):
        return [n for item in value for n in _numbers(item)]
    return []


def _school_with(sessions, *, learners, year_group="JSS 2"):
    """A school, its admin, one class of learners in a year group, one concept."""

    from nevo.db.models.account import Class, School, StudentClassEnrollment, User
    from nevo.db.models.frontend_support import Concept

    async def run():
        async with sessions.begin() as session:
            school = School(
                name="S", school_code=uuid.uuid4().hex[:4].upper(),
                school_url_slug=f"s-{uuid.uuid4().hex[:8]}",
            )
            session.add(school)
            await session.flush()
            admin = User(
                school_id=school.id, role="senco_admin", status="active",
                auth_method="email_password",
                email=f"a-{uuid.uuid4().hex[:6]}@nevolearning-tests.com",
            )
            children = [
                User(
                    school_id=school.id, role="student", status="active", auth_method="pin",
                    login_identifier=f"NV-{uuid.uuid4().hex[:6]}",
                )
                for _ in range(learners)
            ]
            school_class = Class(school_id=school.id, name="2A", year_group=f" {year_group} ")
            concept = Concept(name="mole_calculations", school_id=school.id)
            session.add_all([admin, school_class, concept, *children])
            await session.flush()
            session.add_all(
                StudentClassEnrollment(class_id=school_class.id, student_id=child.id)
                for child in children
            )
            return admin.id, [child.id for child in children], concept.id

    return asyncio.run(run())


def _levels(sessions, student_id, concept_id, rows, *, reading=None):
    """rows: engine level -> (probability, independent passes, supported, practice)."""

    from nevo.db.models.mastery import StudentConceptLevelMastery, StudentConceptMastery

    async def run():
        async with sessions.begin() as session:
            for level, (p, independent, supported, practice) in rows.items():
                session.add(
                    StudentConceptLevelMastery(
                        student_id=student_id, concept_id=concept_id, mastery_level=level,
                        mastery_probability=p, independent_pass_count=independent,
                        supported_pass_count=supported, practice_count=practice,
                    )
                )
            if reading is not None:
                session.add(
                    StudentConceptMastery(
                        student_id=student_id, concept_id=concept_id,
                        mastery_probability_concept=0.5, mastery_probability_reading=reading,
                        practice_count=3,
                    )
                )

    asyncio.run(run())


def test_a_teacher_sees_a_state_for_each_level_observed(me):
    _, _, sessions = me
    admin, (child, *_), concept = _school_with(sessions, learners=1)
    _levels(
        sessions, child, concept,
        {"knowledge": (0.82, 2, 0, 3), "application": (0.3, 0, 1, 2), "analysis": (0.2, 0, 0, 2)},
        reading=0.4,
    )

    response = _get(sessions, f"/api/v1/students/{child}/mastery", admin, "senco_admin")

    assert response.status_code == 200
    body = response.json()
    assert body["concepts"] == [
        {
            "conceptId": str(concept),
            "conceptName": body["concepts"][0]["conceptName"],
            "levels": {
                "knowing_and_understanding": "reached",
                "application": "working",
                "analysis_and_evaluation": "not",
            },
            "reading": "support",
        }
    ]
    assert _numbers(body) == []  # no probability, score or count


def test_a_level_never_observed_is_left_out_not_marked_not(me):
    _, _, sessions = me
    admin, (child, *_), concept = _school_with(sessions, learners=1)
    _levels(sessions, child, concept, {"knowledge": (0.3, 0, 0, 1)})

    concept_read = _get(
        sessions, f"/api/v1/students/{child}/mastery", admin, "senco_admin"
    ).json()["concepts"][0]

    assert concept_read["levels"] == {"knowing_and_understanding": "not"}
    assert "reading" not in concept_read


def test_a_child_cannot_read_the_staff_view(me):
    _, _, sessions = me
    _, (child, *_), _ = _school_with(sessions, learners=1)

    response = _get(sessions, f"/api/v1/students/{child}/mastery", child, "student")

    assert response.status_code == 403


def test_another_schools_learner_is_not_found(me):
    _, _, sessions = me
    _, (child, *_), _ = _school_with(sessions, learners=1)
    other_admin, _, _ = _school_with(sessions, learners=1)

    response = _get(sessions, f"/api/v1/students/{child}/mastery", other_admin, "senco_admin")

    assert response.status_code == 404


def test_a_year_group_is_counted_at_each_learners_highest_level(me):
    _, _, sessions = me
    admin, children, concept = _school_with(sessions, learners=6)
    reached = (0.9, 2, 0, 3)
    for child in children[:2]:
        _levels(sessions, child, concept, {"knowledge": reached})
    _levels(sessions, children[2], concept, {"knowledge": reached, "application": reached})
    for child in children[3:5]:
        _levels(sessions, child, concept, {"knowledge": (0.3, 0, 1, 2)})
    # A gap stops the climb: application without knowledge counts as not yet.
    _levels(sessions, children[5], concept, {"application": reached})

    body = _get(
        sessions, f"/api/v1/reports/year-groups/jss%202/concepts/{concept}/mastery",
        admin, "senco_admin",
    ).json()

    assert body["yearGroup"] == "jss 2"
    assert body["learnerCount"] == 6
    assert body["suppressed"] is False
    assert body["atLevel"] == {
        "knowing_and_understanding": 2,
        "application": 1,
        "analysis_and_evaluation": 0,
    }
    assert body["notYet"] == 3


def test_a_year_group_below_the_floor_is_withheld(me):
    _, _, sessions = me
    admin, children, concept = _school_with(sessions, learners=4)
    for child in children:
        _levels(sessions, child, concept, {"knowledge": (0.9, 2, 0, 3)})

    body = _get(
        sessions, f"/api/v1/reports/year-groups/JSS 2/concepts/{concept}/mastery",
        admin, "senco_admin",
    ).json()

    assert body["suppressed"] is True
    assert body["withheldLabel"] == "Too few to report"
    assert "atLevel" not in body and "notYet" not in body
