"""Adding one child asks their parent, the way a class upload always has.

Lydia's ruling of 6 November: a school pays for the children on its roster
whether or not consent has come back, because the school is the only party
who can chase a parent and a lower bill would be a reason not to. The
removal countdown is the backstop that stops anyone paying indefinitely for
a child who will never start.

That countdown is armed by the consent request, not by the enrolment: the
daily sweep works off invitations that expire unanswered, writes a
no-response refusal at thirty days, and removes the roster entry thirty days
after that. So a child nobody got round to asking about had no countdown at
all - billed on the roster, unable to start a lesson, indefinitely.

A class upload has always asked every parent it was given an address for.
Adding one child recorded the address and left the asking to whoever
remembered. These tests pin that it no longer does.
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from nevo.api import product_admin
from nevo.api.response_models import StudentEnrollmentResponse
from nevo.consent.errors import ParentAlreadyRefusedError
from nevo.consent.expiry import DELETE_ROSTER_AFTER
from nevo.consent.service import DEFAULT_REQUESTED_CONSENT, PARENT_CONSENT_LIFETIME
from nevo.domain.accounts.vocabulary import ConsentType
from nevo.domain.consent.vocabulary import ParentContactMethod


def test_enrolment_requests_consent_when_given_an_address() -> None:
    source = inspect.getsource(product_admin.enroll_student)
    assert "_ask_this_parent_now" in source
    asked = inspect.getsource(product_admin._ask_this_parent_now)
    assert "request_parent_consent" in asked
    # The same set a class upload asks for, so the two routes cannot ask for
    # different things about the same child.
    assert "DEFAULT_REQUESTED_CONSENT" in asked


def test_no_address_means_no_request_rather_than_a_failure() -> None:
    asked = inspect.getsource(product_admin._ask_this_parent_now)
    assert "if not parent_email" in asked


def test_a_failed_request_does_not_undo_the_enrolment() -> None:
    # Enrolment has committed by the time the parent is asked. A child whose
    # parent could not be emailed is still a child the school added, and
    # rolling the enrolment back would lose the admission number they just
    # typed. The response says whether the asking happened instead.
    asked = inspect.getsource(product_admin._ask_this_parent_now)
    assert "return False" in asked
    assert "consent_requested" in StudentEnrollmentResponse.model_fields
    assert StudentEnrollmentResponse.model_fields["consent_requested"].default is False


def test_an_already_refused_parent_is_not_asked_again() -> None:
    # The refusal record exists so a school cannot keep asking someone who
    # said no. Enrolment must not become a way round it, and a refusal
    # reaching this code is the rule working, not an error to report.
    asked = inspect.getsource(product_admin._ask_this_parent_now)
    assert "except ConsentError" in asked


def test_the_countdown_this_arms_is_bounded() -> None:
    # Why the request matters at all: without one there is no invitation to
    # expire, so neither half of the countdown ever starts. Thirty days for
    # the parent, thirty more before the roster entry goes.
    assert PARENT_CONSENT_LIFETIME.days == 30
    assert DELETE_ROSTER_AFTER.days == 30


def test_the_requested_consents_include_the_one_a_child_cannot_start_without() -> None:
    assert ConsentType.DATA_PROCESSING in DEFAULT_REQUESTED_CONSENT


async def _ask(service: object, parent_email: str | None) -> bool:
    actor = SimpleNamespace(id=uuid4(), school_id=uuid4())
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(consent_service=service)))
    return await product_admin._ask_this_parent_now(
        request,  # type: ignore[arg-type]
        actor=actor,  # type: ignore[arg-type]
        student_id=uuid4(),
        parent_email=parent_email,
    )


@pytest.mark.asyncio
async def test_the_parent_is_actually_asked() -> None:
    service = SimpleNamespace(request_parent_consent=AsyncMock())
    assert await _ask(service, "guardian@example.test") is True
    kwargs = service.request_parent_consent.call_args.kwargs
    assert kwargs["parent_contact"] == "guardian@example.test"
    assert kwargs["consent_types"] == DEFAULT_REQUESTED_CONSENT
    assert kwargs["contact_method"] is ParentContactMethod.EMAIL


@pytest.mark.asyncio
async def test_without_an_address_nobody_is_asked() -> None:
    service = SimpleNamespace(request_parent_consent=AsyncMock())
    assert await _ask(service, None) is False
    service.request_parent_consent.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_refusal_is_reported_as_not_asked_and_not_raised() -> None:
    service = SimpleNamespace(
        request_parent_consent=AsyncMock(side_effect=ParentAlreadyRefusedError())
    )
    assert await _ask(service, "guardian@example.test") is False


@pytest.mark.asyncio
async def test_an_unconfigured_consent_service_does_not_fail_the_enrolment() -> None:
    assert await _ask(None, "guardian@example.test") is False
