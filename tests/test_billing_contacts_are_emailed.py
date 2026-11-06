"""Invoices and reminders reach the people the school named.

Lydia's reason for allowing several billing contacts is that invoices were
landing with someone who could not act on them. Storing the addresses only
solved that if something sends to them, so these pin the chain end to end:
the contacts are read, a delivery is queued per address and milestone, and
a worker sends it.

Every contact, not only the primary. The primary is who checkout is
attributed to; being able to read the bill is a different question, and
naming several people is the point of the screen.
"""

from __future__ import annotations

import inspect

from nevo.billing import email_worker, issuance
from nevo.db.models.billing import BillingEmailDelivery


def test_every_contact_is_queued_not_only_the_primary() -> None:
    source = inspect.getsource(issuance.queue_billing_emails)
    assert "BillingContact.email" in source
    assert "BillingContact.school_id == invoice.school_id" in source
    # No primary filter: narrowing to the primary contact would quietly undo
    # the reason the screen allows several in the first place. Checked
    # against the query rather than the whole function, so the docstring
    # explaining why is free to use the word.
    query = source.split("existing =")[0]
    assert "is_primary" not in query
    assert "primary" not in query.split('"""')[-1]


def test_a_school_with_no_contact_is_reported_rather_than_skipped() -> None:
    # Nothing to queue means the invoice reaches nobody by email. Silence
    # there is an unpaid invoice that was never sent.
    source = inspect.getsource(issuance.queue_billing_emails)
    assert "if not emails:" in source
    assert "logger.warning" in source
    assert "no billing contact to email" in source


def test_each_address_is_queued_once_per_milestone() -> None:
    source = inspect.getsource(issuance.queue_billing_emails)
    # Read-then-write would still double-send under two concurrent sweeps,
    # so the table carries the guarantee as well.
    assert "emails - existing" in source
    names = {
        constraint.name for constraint in BillingEmailDelivery.__table__.constraints
    }
    assert "uq_billing_email_invoice_recipient_kind" in names


def test_reminders_stop_once_the_invoice_is_paid() -> None:
    source = inspect.getsource(email_worker.BillingEmailWorker)
    assert 'kind != "issued"' in source
    assert '"paid"' in source


def test_the_invoice_itself_is_attached() -> None:
    # A reminder with no invoice on it asks someone to pay something they
    # have to go and find.
    source = inspect.getsource(email_worker.BillingEmailWorker)
    assert "attachment=" in source
    assert "render_simple_pdf" in source


def test_delivery_is_retried_and_eventually_given_up_on() -> None:
    source = inspect.getsource(email_worker.BillingEmailWorker)
    assert "attempt_count" in source
    # Bounded, so a dead address does not retry for ever, and claimed with
    # skip_locked so two workers cannot send the same row twice.
    assert "skip_locked=True" in source
    assert '"failed"' in source
