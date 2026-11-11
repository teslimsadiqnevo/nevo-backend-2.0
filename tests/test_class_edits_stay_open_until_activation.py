"""A school can still fix a class name while it is waiting to pay.

Renaming, dropping and merging were refused the moment the roster was
confirmed, with 409 onboarding_already_confirmed. But Confirm only creates the
classes and lets the invoice be raised - nothing is live and nobody is billed
until payment, and a Nigerian school paying by transfer can sit in
awaiting_payment for days. So a typo spotted in that window could not be
fixed: the school waited for activation to correct a name, or kept it.

Lydia, 11 November: these stay open until something is activated.

Re-uploading a file is deliberately not included. That rebuilds a list the
school has already agreed to, and the classes and people derived from the
first one already exist.
"""

from __future__ import annotations

import pytest

from nevo.api.onboarding import EDITABLE_STAGES
from nevo.domain.onboarding.vocabulary import OnboardingStage


@pytest.mark.parametrize(
    "stage",
    [OnboardingStage.UPLOADING, OnboardingStage.CONFIRMED, OnboardingStage.AWAITING_PAYMENT],
)
def test_a_class_can_be_edited_up_to_activation(stage: OnboardingStage) -> None:
    assert stage in EDITABLE_STAGES


def test_an_activated_school_is_refused() -> None:
    """Once people are live, a change belongs in the admin console.

    Editing here would move students between classes that are already
    billed, which is what the refusal has always been protecting.
    """
    assert OnboardingStage.ACTIVATED not in EDITABLE_STAGES


def test_every_stage_is_accounted_for() -> None:
    """A new stage must be a decision, not an accident of this tuple."""
    assert set(EDITABLE_STAGES) | {OnboardingStage.ACTIVATED} == set(OnboardingStage)


def test_both_decision_routes_use_the_same_gate() -> None:
    from nevo.api import onboarding

    source = onboarding.__loader__.get_source(onboarding.__name__)
    assert source.count("if record.stage not in EDITABLE_STAGES:") == 2
    correct = source.index("async def correct_derived_classes")
    merges = source.index("async def decide_class_merges")
    for start in (correct, merges):
        body = source[start : start + 1600]
        assert "EDITABLE_STAGES" in body


def test_uploading_a_new_file_is_still_closed_after_confirm() -> None:
    """The one that was not opened, and why."""
    from nevo.api import onboarding

    source = onboarding.__loader__.get_source(onboarding.__name__)
    start = source.index("async def stage_import")
    # Up to the constant, which now sits between the two functions.
    body = source[start : source.index("#: Stages in which a school", start)]
    assert "if record.stage is not OnboardingStage.UPLOADING:" in body
    assert "EDITABLE_STAGES" not in body


def test_the_refusal_says_running_rather_than_confirmed() -> None:
    """The old code and message said confirmed, which is no longer the bar."""
    from nevo.api import onboarding

    source = onboarding.__loader__.get_source(onboarding.__name__)
    start = source.index("async def correct_derived_classes")
    body = source[start : source.index("async def decide_class_merges", start)]
    assert "onboarding_already_activated" in body
    assert "onboarding_already_confirmed" not in body
    assert "billed twice" in body
