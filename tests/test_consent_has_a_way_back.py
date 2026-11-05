"""A withdrawal must be reversible by the parent who made it.

Withdrawal was terminal, and by accident rather than by policy. Three
separate guards each correctly refuse to overrule a withdrawal:

  * the school's confirm paths only lift a pending record,
  * the written consent form refuses a withdrawn one outright,
  * and the withdrawal writes a ConsentRefusal, which stops the school
    sending the same parent another request.

Each is right on its own. Together they left no route back at all, so a
parent who changed their mind had to ask the school to do the one thing the
school is specifically forbidden to do. These tests pin the way back, and
pin that it is the withdrawing parent's alone.
"""

from __future__ import annotations

import inspect

from nevo.api import parent_rights, product_auth
from nevo.domain.consent.vocabulary import ParentRightType


def test_restoring_is_a_named_right_not_an_untyped_string() -> None:
    # Stored in a String(40) column, so a bare "restore_consent" would have
    # worked and been invisible to the rights log's own filter.
    assert ParentRightType.RESTORE_CONSENT.value == "restore_consent"
    assert ParentRightType("restore_consent") is ParentRightType.RESTORE_CONSENT


def test_the_parent_account_offers_a_route_back() -> None:
    route = next(
        r
        for r in parent_rights.router.routes
        if getattr(r, "path", "").endswith("/consents/restore")
    )
    assert "POST" in route.methods


def test_restore_reattributes_the_consent_instead_of_half_writing_it() -> None:
    # consent_records has a check constraint - confirmation_fields_match_status
    # - that allows exactly one source with exactly the actor that goes with
    # it. A record withdrawn after the school confirmed it still carries the
    # admin id, so setting a parent id and leaving that in place satisfies
    # neither branch and the commit fails. All four fields move together.
    source = inspect.getsource(parent_rights.restore_consent)
    assert "ConsentConfirmationSource.PARENT" in source
    assert "record.confirmed_by_admin_id = None" in source
    assert "record.confirmed_via = ConsentMethod.DIGITAL" in source
    assert "record.confirmed_at = now" in source


def test_restore_clears_the_refusal_that_would_block_the_next_request() -> None:
    # The refusal is a standing "do not ask this parent again". Leaving it
    # after they have said yes would block next term's request for a consent
    # that is now given.
    assert "_clear_refusal" in inspect.getsource(parent_rights.restore_consent)
    clear = inspect.getsource(parent_rights._clear_refusal)
    assert "ConsentRefusalReason.WITHDRAWN" in clear
    assert "session.delete" in clear


def test_restore_reactivates_only_for_the_consent_that_stops_access() -> None:
    source = inspect.getsource(parent_rights.restore_consent)
    assert "REQUIRED_LEARNING_CONSENT in restored" in source
    # Guarded on DEACTIVATED rather than set unconditionally: a child
    # deactivated for some other reason is not reactivated by a consent.
    assert "student.status is UserStatus.DEACTIVATED" in source


def test_one_guardian_cannot_undo_anothers_withdrawal() -> None:
    # The mirror of the 5 November ruling, and the worse direction of the
    # two: this one would put a child back into processing that the person
    # responsible for them had stopped.
    guard = inspect.getsource(parent_rights._refuse_restoring_another_parents_consent)
    assert "last_actor_user_id is not None" in guard
    assert "last_actor_user_id != parent_id" in guard
    assert "withdrawal_belongs_to_another_guardian" in guard
    assert "_refuse_restoring_another_parents_consent" in inspect.getsource(
        parent_rights.restore_consent
    )


def test_restoring_nothing_is_a_conflict_not_a_silent_success() -> None:
    source = inspect.getsource(parent_rights.restore_consent)
    assert "nothing_to_restore" in source


def test_a_restore_reports_restored_types_not_withdrawn_ones() -> None:
    assert "restored_types" in parent_rights.RightOutcome.model_fields
    assert "restored_types=sorted(restored" in inspect.getsource(parent_rights.restore_consent)


def test_an_email_link_cannot_give_a_child_their_access_back() -> None:
    # The consent token is a link in an email that may be months old and
    # forwarded. It is enough to withdraw, which fails safe, and not enough
    # to restore, which does not.
    source = inspect.getsource(product_auth.exercise_parent_right)
    assert "ParentRightType.RESTORE_CONSENT" in source
    assert "restore_requires_parent_account" in source
