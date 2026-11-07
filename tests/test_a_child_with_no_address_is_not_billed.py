"""A child nobody can act on yet does not enter the billed count.

SCRUM-309, Lydia's ruling of 7 November. The roster is billed whether or not
consent has come back, because the school is the only party who can chase a
parent and a lower bill would be a reason not to. The removal countdown is
what stops anyone paying indefinitely for a child who never starts.

A child added with no parent address has nothing to send, so no consent
request exists and no countdown has started. They would sit on the roster
being billed with nothing counting down - the same indefinite billing by a
different door. They enter the count the day an address is added and the
request goes out.

Her words: this is not the school being let off, it is a child nobody can
act on yet. The screen listing them stays, because somebody has to add the
address.
"""

from __future__ import annotations

import inspect

from nevo.billing.issuance import InvoiceIssuanceService
from nevo.consent.expiry import DELETE_ROSTER_AFTER
from nevo.consent.service import PARENT_CONSENT_LIFETIME


def test_the_count_requires_a_parent_address() -> None:
    source = inspect.getsource(InvoiceIssuanceService._billable_students)
    assert "ParentLink.student_id == User.id" in source
    # Present and non-empty: enrolment writes a link with a blank name for
    # the parent to fill in, so the link existing is not the same as an
    # address existing.
    assert 'ParentLink.parent_contact != ""' in source
    assert ".exists()" in source


def test_the_roster_is_otherwise_still_billed() -> None:
    # Both states. A consent that has not come back does not reduce the
    # bill, which is the standing ruling this is the exception to.
    source = inspect.getsource(InvoiceIssuanceService._billable_students)
    assert "UserStatus.ACTIVE, UserStatus.INVITED" in source


def test_a_withdrawn_child_is_still_outside_the_count() -> None:
    # Withdrawal deactivates, and DEACTIVATED is in neither state above, so
    # a withdrawn child stays off the bill - the school cannot overrule it,
    # cannot ask again and cannot act on it.
    from nevo.domain.accounts.vocabulary import UserStatus

    source = inspect.getsource(InvoiceIssuanceService._billable_students)
    assert UserStatus.DEACTIVATED.value not in source


def test_the_countdown_this_protects_is_still_bounded() -> None:
    # Why an address matters: without a request there is no invitation to
    # expire, so neither half of the countdown ever starts.
    assert PARENT_CONSENT_LIFETIME.days == 30
    assert DELETE_ROSTER_AFTER.days == 30
