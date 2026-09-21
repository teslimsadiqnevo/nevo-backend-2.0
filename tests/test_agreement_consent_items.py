"""The four obligations the school agreement adds, and what they mean in code.

Each of these was "nobody owns this" a week ago: a thirty-day consent window,
a two-point age check, a separate consent for the transfer outside Nigeria,
and withdrawal that is no harder than consenting.
"""

from __future__ import annotations

import inspect
from datetime import timedelta

import pytest

from nevo.api import parent_rights
from nevo.consent.expiry import DELETE_ROSTER_AFTER, ConsentExpiryService, contact_digest
from nevo.consent.service import DEFAULT_REQUESTED_CONSENT, PARENT_CONSENT_LIFETIME
from nevo.db.models.account import ConsentRecord
from nevo.db.models.consent_assurance import AgeCheck, ConsentRefusal
from nevo.domain.accounts.vocabulary import ConsentType
from nevo.domain.consent.vocabulary import AgeCheckState, ConsentRefusalReason
from nevo.main import app


@pytest.fixture(scope="module")
def spec() -> dict:
    return app.openapi()


# ----------------------------------------------------------- 30-day expiry


def test_a_parent_has_thirty_days_to_answer() -> None:
    assert PARENT_CONSENT_LIFETIME == timedelta(days=30)


def test_roster_data_goes_thirty_days_after_that() -> None:
    assert DELETE_ROSTER_AFTER == timedelta(days=30)


def test_the_sweep_runs_daily() -> None:
    from nevo.ops.scheduled_jobs import build_scheduled_jobs

    source = inspect.getsource(build_scheduled_jobs)

    assert "consent.expire_unanswered" in source


def test_a_parent_who_answered_late_keeps_their_child_on_the_roster() -> None:
    source = inspect.getsource(ConsentExpiryService._remove_expired_rosters)

    # Answering after the link expired is still answering.
    assert "_consent_arrived_late" in source


def test_the_refusal_that_survives_cannot_be_read_back_as_a_contact_list() -> None:
    columns = {column.name for column in ConsentRefusal.__table__.columns}

    assert "contact_digest" in columns
    assert "parent_contact" not in columns
    assert "parent_name" not in columns
    # A fingerprint recognises the same parent; it does not reach them.
    assert contact_digest(" Ngozi@Example.com ") == contact_digest("ngozi@example.com")
    assert len(contact_digest("a@b.com")) == 64


def test_a_refusal_outlives_the_learner_row_it_refers_to() -> None:
    # Not a foreign key on purpose: a refusal deleted with the learner would
    # let the school ask the same parent again the next morning.
    assert not ConsentRefusal.__table__.c.student_id.foreign_keys


def test_the_reasons_cover_how_a_request_can_end() -> None:
    assert {reason.value for reason in ConsentRefusalReason} == {
        "no_response",
        "declined",
        "withdrawn",
    }


# ------------------------------------------------------- cross-border consent


def test_the_transfer_out_of_nigeria_is_its_own_consent() -> None:
    assert ConsentType.CROSS_BORDER_TRANSFER.value == "cross_border_transfer"
    assert ConsentType.CROSS_BORDER_TRANSFER is not ConsentType.DATA_PROCESSING


def test_a_parent_is_asked_both_questions_by_default() -> None:
    assert DEFAULT_REQUESTED_CONSENT == frozenset(
        {ConsentType.DATA_PROCESSING, ConsentType.CROSS_BORDER_TRANSFER}
    )


def test_nothing_is_pre_selected(spec: dict) -> None:
    schema = spec["components"]["schemas"]["CompleteParentConsentRequest"]

    # grantedTypes is required and has no default: a missing list is a client
    # bug, not a parent agreeing to whatever was asked.
    assert "grantedTypes" in schema["required"]
    assert "default" not in schema["properties"]["grantedTypes"]


def test_only_what_the_parent_ticked_is_confirmed() -> None:
    from nevo.consent.repositories import SqlAlchemyConsentRepository

    source = inspect.getsource(SqlAlchemyConsentRepository.complete_parent_request)

    assert "granted = consent_types & granted_types" in source
    assert "declined = consent_types - granted_types" in source


def test_the_completion_reports_both_answers(spec: dict) -> None:
    fields = spec["components"]["schemas"]["ParentConsentCompletionResponse"]["properties"]

    assert {"confirmedTypes", "declinedTypes", "ageCheck"} <= set(fields)


# ------------------------------------------------------------- age check


def test_the_two_sources_are_kept_apart() -> None:
    columns = {column.name for column in AgeCheck.__table__.columns}

    # The school's date and the parent's are both kept, so a disagreement can
    # be shown rather than silently resolved in favour of one of them.
    assert {"school_date_of_birth", "parent_date_of_birth", "agreed_date_of_birth"} <= columns


def test_a_mismatch_blocks_and_a_match_does_not() -> None:
    assert AgeCheck(state=AgeCheckState.MISMATCH).blocks_access
    assert not AgeCheck(state=AgeCheckState.MATCHED).blocks_access
    assert not AgeCheck(state=AgeCheckState.RESOLVED).blocks_access


def test_a_roster_with_no_date_of_birth_is_not_treated_as_agreement() -> None:
    from nevo.consent.repositories import SqlAlchemyConsentRepository

    source = inspect.getsource(SqlAlchemyConsentRepository._run_age_check)

    assert "school_date is None or school_date != parent_date_of_birth" in source


def test_the_child_is_never_asked_and_the_school_settles_it(spec: dict) -> None:
    assert "get" in spec["paths"]["/api/v1/age-checks"]
    assert "post" in spec["paths"]["/api/v1/age-checks/{age_check_id}/resolve"]

    from nevo.api.student_entry import set_pin_and_start

    entry = inspect.getsource(set_pin_and_start)
    # The child is told the school is checking something, and asked nothing.
    assert "age_check_blocks" in entry
    assert "age_check_pending" in entry


def test_resolving_records_who_closed_it() -> None:
    columns = {column.name for column in AgeCheck.__table__.columns}

    assert {"resolved_by_user_id", "resolved_at", "resolution_note"} <= columns


# ------------------------------------------------------------- withdrawal


def test_a_parent_can_withdraw_from_their_own_account(spec: dict) -> None:
    # Not from a link that expires. A parent who consented in September and
    # changed their mind in November had no route at all.
    assert "get" in spec["paths"]["/api/v1/parents/me/consents"]
    assert "post" in spec["paths"]["/api/v1/parents/me/consents/withdraw"]
    assert "post" in spec["paths"]["/api/v1/parents/me/objections"]
    assert "post" in spec["paths"]["/api/v1/parents/me/data-requests"]


def test_withdrawal_needs_no_token() -> None:
    source = inspect.getsource(parent_rights.withdraw_consent)

    assert "token" not in source
    assert "ParentDependency" in inspect.getsource(parent_rights)


def test_a_parent_sees_what_a_withdrawal_will_do_before_pressing_it(
    spec: dict,
) -> None:
    fields = spec["components"]["schemas"]["ConsentHeld"]["properties"]

    assert "stopsAccess" in fields


def test_withdrawing_the_learning_consent_stops_the_child() -> None:
    source = inspect.getsource(parent_rights.withdraw_consent)

    assert "UserStatus.DEACTIVATED" in source
    # Withdrawing only the cross-border consent does not stop them learning.
    assert "REQUIRED_LEARNING_CONSENT in withdrawn" in source


def test_objecting_is_not_the_same_as_withdrawing() -> None:
    source = inspect.getsource(parent_rights.object_to_processing)

    assert "ParentRightType.OBJECT" in source
    assert "DEACTIVATED" not in source


def test_a_parent_can_only_reach_their_own_child() -> None:
    source = inspect.getsource(parent_rights._own_child)

    assert "ParentLink.parent_id == parent_id" in source


def test_the_consent_record_now_carries_the_missing_definition_fields() -> None:
    columns = {column.name for column in ConsentRecord.__table__.columns}

    # Identity, relationship, date, method, notice version.
    assert {
        "parent_name_on_form",
        "parent_relationship",
        "notice_version",
        "confirmed_via",
        "confirmed_at",
    } <= columns
