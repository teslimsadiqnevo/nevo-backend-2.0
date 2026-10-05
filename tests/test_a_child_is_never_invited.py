"""A child is never sent a link. SCRUM-215.

A child has no email address: they are identified by their Student ID, scoped
by their school's four-character code, and authenticated by a PIN. They appear
on the roster when the school uploads it and they join through their teacher,
who reads the code out.

So an endpoint that accepted an invitation for a student could only do one of
two things - send mail to nobody, or send a child's join link to a parent's
address - and neither is a path anybody designed. The invitation machinery
shipped accepting the role anyway, which is what this closes.

The parent consent link is unaffected. That is a parent path, tokenised per
parent-and-child pair, and it is the only link that goes out on a child's
behalf.
"""

from __future__ import annotations

import inspect

from nevo.api.product_auth import (
    _refuse_student_invitation,
    accept_join,
    inspect_join,
    resend_invite,
)
from nevo.domain.accounts.vocabulary import InvitableRole, UserRole
from nevo.main import app


def test_a_student_is_not_an_invitable_role() -> None:
    assert [role.value for role in InvitableRole] == ["teacher"]
    # Still a real role everywhere else - children exist, they are just not
    # invited into existence.
    assert UserRole.STUDENT.value == "student"


def test_the_invite_contract_offers_only_teacher() -> None:
    schema = app.openapi()["components"]["schemas"]

    assert schema["InvitableRole"]["enum"] == ["teacher"]


def test_a_stale_student_row_is_refused_loudly_not_quietly() -> None:
    import pytest
    from fastapi import HTTPException

    # Refused rather than accepted and no-opped, so a caller that has not
    # caught up fails where somebody can see it.
    with pytest.raises(HTTPException) as refusal:
        _refuse_student_invitation("student")

    assert refusal.value.status_code == 409
    assert refusal.value.detail["code"] == "student_not_invitable"
    # A teacher row passes straight through.
    assert _refuse_student_invitation("teacher") is None


def test_every_door_a_stale_student_row_could_reach_refuses_it() -> None:
    # The role is a stored string, so a row written before this ticket can
    # still be reached even though none can be created now.
    for route in (resend_invite, inspect_join, accept_join):
        assert "_refuse_student_invitation" in inspect.getsource(route), route.__name__


def test_the_parent_consent_link_is_untouched() -> None:
    paths = app.openapi()["paths"]

    # The one link that goes out on a child's behalf, and it is a parent's.
    assert "/api/v1/consents/parent/{token}" in paths
    assert "/api/v1/consents/parent/complete" in paths
