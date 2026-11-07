"""The parent token read says enough to route a returning parent.

The consent link is the only thing a parent arrives with, and the read behind
it answered one question: what are you being asked to agree to. Two things it
did not say, both reported from the console on 6 November.

Whether this guardian already has an account, so a parent coming back is sent
to sign in rather than through setting a password they have. The consent
status could not stand in for it: a confirmed consent says nothing about
whether an account was ever created.

And where the child's date of birth stands. A parent arriving on a held child
needs the recheck screen rather than the consent form, and nothing in this
response said the child was held.
"""

from __future__ import annotations

from nevo.api.consent import ParentConsentInvitationResponse
from nevo.consent.entities import ParentInvitationView
from nevo.domain.consent.vocabulary import AgeCheckState
from nevo.main import app

SPEC = app.openapi()


def test_the_read_carries_both_routing_facts() -> None:
    properties = SPEC["components"]["schemas"]["ParentConsentInvitationResponse"]["properties"]
    assert "parentAccountReady" in properties
    assert "ageCheck" in properties
    assert "ageCheckHoldReasons" in properties


def test_no_age_check_is_null_rather_than_a_state() -> None:
    # Most children have no check at all. None is the answer, not a state
    # standing in for one, so a screen does not have to read "matched" as
    # "nothing was ever compared".
    assert ParentInvitationView.__dataclass_fields__["age_check_state"].default is None
    assert ParentConsentInvitationResponse.model_fields["age_check"].default is None


def test_a_hold_reason_distinguishes_a_roster_gap_from_a_disagreement() -> None:
    # enrolled_age_band_unavailable means the child is in no class, or in
    # classes spanning two bands, so the band check could not run. The two
    # adults may agree entirely. A screen that cannot tell them apart tells a
    # parent their date is disputed when it is not.
    field = ParentConsentInvitationResponse.model_fields["age_check_hold_reasons"]
    assert field.alias == "ageCheckHoldReasons"
    description = field.description or ""
    assert "enrolled_age_band_unavailable" in description


def test_the_state_vocabulary_is_published_not_a_free_string() -> None:
    # A client routing on this needs the closed set, not to discover it by
    # being surprised.
    assert "AgeCheckState" in SPEC["components"]["schemas"]
    assert set(SPEC["components"]["schemas"]["AgeCheckState"]["enum"]) == {
        state.value for state in AgeCheckState
    }


def test_account_ready_is_decided_by_the_account_not_the_consent() -> None:
    import inspect

    from nevo.consent.repositories import SqlAlchemyConsentRepository

    source = inspect.getsource(SqlAlchemyConsentRepository.parent_invitation)
    assert "parent_link.parent_id is not None" in source
