"""SCRUM-310 and SCRUM-311, which were not built.

310, one invoice reminder after the due date. There were two reminders, seven
days before and on the day, and nothing afterwards: an invoice could sit
unpaid indefinitely with the school never hearing again.

311, the last billing contact could be removed. The route reassigned the
primary when you deleted the primary, but deleting the only one left the
school with nobody to invoice and billing_contact_id null. An invoice would
then be issued and queued to an empty recipient list, and the only sign would
be a zero in the email worker's count.
"""

from __future__ import annotations

from nevo.api import billing
from nevo.billing import email_worker
from nevo.ops import scheduled_jobs


def _removal_source() -> str:
    source = billing.__loader__.get_source(billing.__name__)
    start = source.index("async def remove_billing_contact")
    return source[start : source.index("class StartPaymentRequest", start)]


def _reminder_source() -> str:
    source = scheduled_jobs.__loader__.get_source(scheduled_jobs.__name__)
    start = source.index("async def invoice_reminders")
    return source[start : source.index("async def attention_digests", start)]


def test_the_last_billing_contact_is_refused() -> None:
    body = _removal_source()
    assert "last_billing_contact" in body
    assert "409" in body


def test_the_refusal_counts_the_others_rather_than_assuming() -> None:
    """It has to be the last one specifically, not any primary."""
    body = _removal_source()
    assert "func.count(BillingContact.id)" in body
    assert "BillingContact.id != record.id" in body


def test_the_refusal_says_what_to_do_instead() -> None:
    body = _removal_source()
    assert "Add another one" in body
    assert "cannot be invoiced" in body


def test_removing_a_non_last_contact_still_reassigns_the_primary() -> None:
    """The behaviour that was already right must survive the new guard."""
    body = _removal_source()
    assert "school.billing_contact_id = replacement" in body
    # And the guard comes first, so the reassignment is never reached for the last.
    assert body.index("last_billing_contact") < body.index(
        "school.billing_contact_id = replacement"
    )


def test_an_overdue_invoice_gets_a_reminder() -> None:
    body = _reminder_source()
    assert "reminder_overdue" in body
    assert "invoice.due_at < today" in body


def test_the_overdue_reminder_does_not_displace_the_existing_two() -> None:
    body = _reminder_source()
    assert "reminder_7d" in body
    assert "reminder_due" in body
    # elif, so a due-today invoice is not also treated as overdue.
    assert "elif invoice.due_at < today:" in body


def test_only_one_overdue_reminder_is_ever_sent() -> None:
    """Which is the whole of SCRUM-310, and it rests on existing behaviour.

    queue_billing_emails refuses a second of the same kind for the same
    invoice and address, so the daily job cannot turn one reminder into
    thirty. That guarantee is asserted here because the new code depends on
    it rather than re-implementing it.
    """
    from nevo.billing import issuance

    source = issuance.__loader__.get_source(issuance.__name__)
    queue = source[source.index("async def queue_billing_emails") :]
    assert "BillingEmailDelivery.kind == kind" in queue
    assert "emails - existing" in queue


def test_an_overdue_reminder_says_it_is_overdue() -> None:
    """ "Payment reminder" for a date that has passed reads as though it hasn't."""
    source = email_worker.__loader__.get_source(email_worker.__name__)
    assert '"Overdue payment reminder"' in source
    assert 'kind == "reminder_overdue"' in source


def test_a_paid_invoice_is_never_chased() -> None:
    """Already true, and the new kind must not slip past it."""
    source = email_worker.__loader__.get_source(email_worker.__name__)
    assert 'kind != "issued" and invoice.status.value == "paid"' in source
