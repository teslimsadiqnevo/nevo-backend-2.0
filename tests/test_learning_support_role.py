"""The deepest per-child view is held by somebody, deliberately.

If the registering administrator gets it automatically, every school begins
with its proprietor holding the accommodations, adaptation history and
help-seeking of every child in it. That is the risk this exists to prevent.
"""

from __future__ import annotations

import inspect

import pytest

from nevo.api.learning_support import (
    require_learning_support,
    require_learning_support_if_admin,
)
from nevo.api.product_auth import register_school
from nevo.db.models.permission import LearningSupportGrant
from nevo.domain.permissions.vocabulary import PermissionScope
from nevo.main import app


@pytest.fixture(scope="module")
def spec() -> dict:
    return app.openapi()


def test_registration_does_not_hand_out_the_learning_support_scope() -> None:
    source = inspect.getsource(register_school)

    assert "if scope is not PermissionScope.SENCO" in source
    assert PermissionScope.SENCO.value == "senco"


def test_a_grant_records_who_when_and_by_whom() -> None:
    columns = {column.name for column in LearningSupportGrant.__table__.columns}

    assert {"holder_user_id", "granted_by_user_id", "granted_at"} <= columns
    # Revocations are rows too: "who could see this in March" is a question
    # a deleted row cannot answer.
    assert {"revoked_at", "revoked_by_user_id", "handed_over"} <= columns


def test_a_handover_is_not_the_same_fact_as_a_revocation() -> None:
    columns = {column.name for column in LearningSupportGrant.__table__.columns}

    assert "handed_over" in columns


def test_the_holders_are_exposed_for_the_compliance_screen(spec: dict) -> None:
    assert "get" in spec["paths"]["/api/v1/learning-support/holders"]
    fields = spec["components"]["schemas"]["LearningSupportHolder"]["properties"]

    assert {"name", "grantedAt", "grantedBy"} <= set(fields)


def test_the_role_can_be_granted_handed_over_and_taken_back(spec: dict) -> None:
    assert "post" in spec["paths"]["/api/v1/learning-support/holders"]
    assert "delete" in spec["paths"]["/api/v1/learning-support/holders/{user_id}"]
    fields = spec["components"]["schemas"]["GrantRequest"]["properties"]

    # Nevo does not decide a handover silently in either direction.
    assert "replaceExisting" in fields


def test_the_refusal_comes_from_the_api_not_from_hidden_navigation() -> None:
    source = inspect.getsource(require_learning_support)

    assert "learning_support_role_required" in source
    assert "403" in source or "HTTP_403_FORBIDDEN" in source


def test_a_teacher_is_unaffected() -> None:
    # A class teacher opening their own pupil is not what this changes.
    source = inspect.getsource(require_learning_support_if_admin)

    assert "ADMIN_ROLES" in source


@pytest.mark.parametrize(
    "handler",
    [
        ("nevo.api.product_learning", "student_profile"),
        ("nevo.api.insights", "student_adaptations"),
    ],
    ids=["learner profile", "adaptation history"],
)
def test_the_deep_per_child_reads_are_gated(handler: tuple[str, str]) -> None:
    import importlib

    module = importlib.import_module(handler[0])
    source = inspect.getsource(getattr(module, handler[1]))

    assert "require_learning_support_if_admin" in source
