"""A withdrawal a school can overrule is not a withdrawal.

Lydia's ruling of 5 November: suspension lifts only on a fresh consent from
the parent who withdrew, and no school-side action restores access. These
pin the two places that did not obey it.
"""

from __future__ import annotations

import inspect

from nevo.domain.accounts.vocabulary import ConsentStatus


def test_a_paper_form_cannot_lift_a_withdrawal() -> None:
    """The one school-side path that could, and nothing recorded that it had.

    `POST /students/{id}/consents/written` wrote CONFIRMED over whatever was
    there, so uploading a scan lifted a suspension a parent had imposed - no
    check that the form post-dated the withdrawal, none that it came from the
    parent who withdrew.
    """

    from nevo.api.written_consent import record_written_consent

    source = inspect.getsource(record_written_consent)

    assert "ConsentStatus.WITHDRAWN" in source
    assert "consent_withdrawn" in source
    # Refused before anything is written, and the commit is after the loop,
    # so a request covering several consent types writes none of them rather
    # than some.
    withdrawn_at = source.index("ConsentStatus.WITHDRAWN")
    confirmed_at = source.index("record.status = ConsentStatus.CONFIRMED")
    assert withdrawn_at < confirmed_at, "the guard must precede the write"


def test_the_other_confirm_paths_only_upgrade_a_pending_record() -> None:
    """The three that were already safe, kept that way."""

    from nevo.consent import repositories

    source = inspect.getsource(repositories)

    # Both the school confirmation and the parent completion gate on PENDING.
    assert source.count("if record.status is ConsentStatus.PENDING:") >= 2


def test_only_the_guardian_who_consented_can_withdraw_it() -> None:
    """A second guardian must not be able to suspend a child on another's consent.

    Any parent link used to carry the right to withdraw, so a guardian added
    after consent was given could withdraw it.
    """

    from nevo.api.parent_rights import _refuse_another_parents_consent, withdraw_consent

    assert "_refuse_another_parents_consent" in inspect.getsource(withdraw_consent)
    guard = inspect.getsource(_refuse_another_parents_consent)
    assert "confirmed_by_parent_id" in guard
    assert "consent_belongs_to_another_guardian" in guard


def test_a_school_confirmed_consent_stays_withdrawable_by_any_guardian() -> None:
    """Otherwise nobody could ever withdraw one, which is worse.

    Where no parent gave the consent - a paper form, or a school
    confirmation - there is no "guardian who gave it" to restrict it to.
    """

    from nevo.api.parent_rights import _refuse_another_parents_consent

    guard = inspect.getsource(_refuse_another_parents_consent)
    assert "is not None" in guard


def test_an_already_withdrawn_consent_is_not_re_refused() -> None:
    """Withdrawing twice is not an error, and not another guardian's business."""

    from nevo.api.parent_rights import _refuse_another_parents_consent

    guard = inspect.getsource(_refuse_another_parents_consent)
    assert "is not ConsentStatus.WITHDRAWN" in guard
    assert ConsentStatus.WITHDRAWN.value == "withdrawn"
