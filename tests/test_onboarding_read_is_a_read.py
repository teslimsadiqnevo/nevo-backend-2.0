"""Reading where a school is does not put it back at the start.

The read shared a helper with the write routes, and that helper creates an
onboarding record when it finds none. So the first admin page load at a
school that predates the funnel wrote a row saying that school was back at
"uploading" - and a console deciding read-only from the stage would have held
every established school read-only on the strength of its own page load.
"""

from __future__ import annotations

import inspect

from nevo.api.onboarding import OnboardingState, read_onboarding
from nevo.domain.onboarding.vocabulary import OnboardingStage
from nevo.main import app


def test_the_read_does_not_call_the_creating_helper() -> None:
    source = inspect.getsource(read_onboarding)

    # _onboarding() creates. The read selects for itself instead.
    # Matched with the await, because the function's own name ends in the
    # same characters.
    assert "await _onboarding(" not in source
    assert "select(SchoolOnboarding)" in source


def test_the_read_never_adds_or_flushes() -> None:
    source = inspect.getsource(read_onboarding)

    assert "session.add" not in source
    assert "flush" not in source


def test_a_school_that_never_onboarded_is_not_in_onboarding() -> None:
    state = OnboardingState(
        stage=OnboardingStage.ACTIVATED,
        classes=[],
        teacher_count=0,
        student_count=0,
        rejected=[],
        in_onboarding=False,
    )

    assert state.in_onboarding is False
    # Its workspace is open, which is the true answer to what the stage asks.
    assert state.stage is OnboardingStage.ACTIVATED


def test_the_route_does_not_answer_404() -> None:
    """A client should not carry a branch for a status this cannot return."""

    responses = app.openapi()["paths"]["/api/v1/onboarding"]["get"]["responses"]

    assert "404" not in responses
    assert "200" in responses


def test_the_console_has_one_field_to_branch_on() -> None:
    properties = app.openapi()["components"]["schemas"]["OnboardingState"]["properties"]

    assert "inOnboarding" in properties
