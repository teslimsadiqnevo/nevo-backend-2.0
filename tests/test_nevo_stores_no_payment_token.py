"""Nevo stores no reusable payment token, and charges nothing unattended.

Lydia's rule, in writing, 22 November 2026:

    Nevo stores no reusable payment token for any customer, school or
    individual, and no path charges a stored instrument with nobody present.
    Schools pay by invoice and bank transfer, so there is no card to
    tokenise. Individual learners buy a month at a time through Paystack
    checkout with card, transfer and USSD all available, and buy again when
    it lapses, so there is nothing to store there either.

This is written as a test rather than a note because the code had all of it
and nobody had asked for any of it. A successful payment stored the token by
itself, a route let a client store one by asking, and a daily job charged
against it with nobody present - 52 runs, and on 22 November it attempted
two real invoices, 150,500 and 6,450,000. Nothing was collected. The attempt
is the problem.

If any of these fail, the capability came back.
"""

from __future__ import annotations

import inspect

from nevo.api import billing as billing_api
from nevo.billing import repositories as billing_repositories
from nevo.ops import scheduled_jobs
from nevo.payments import paystack, repositories, service


def test_there_is_no_way_to_charge_with_nobody_present() -> None:
    # The methods, not the word: the comment that records why they went
    # necessarily names them.
    assert not hasattr(service.PaymentService, "charge_saved_method")
    assert not hasattr(paystack.PaystackClient, "charge_authorization")
    # And the provider endpoint that does it is not reachable from here.
    assert "transaction/charge_authorization" not in inspect.getsource(paystack)


def test_nothing_reads_a_stored_token_back() -> None:
    repo = repositories.SqlAlchemyPaymentRepository
    assert not hasattr(repo, "saved_method")
    assert not hasattr(repo, "_upsert_payment_method")


def test_a_successful_payment_stores_nothing_from_the_authorization() -> None:
    """This is how a stored instrument came to exist at all: nobody asked for
    one, a successful payment created it."""
    source = inspect.getsource(repositories.SqlAlchemyPaymentRepository.settle)
    assert "return invoice_paid, False" in source
    assert "authorization.reusable" not in source
    assert "authorization_code" not in source


def test_the_billing_route_cannot_be_asked_to_store_a_token() -> None:
    assert "processor_payment_method_ref" not in billing_api.PaymentMethodRequest.model_fields
    assert (
        "processorPaymentMethodRef"
        not in inspect.getsource(billing_api.update_payment_method)
    )


def test_an_update_clears_a_token_that_predates_the_rule() -> None:
    source = inspect.getsource(billing_repositories)
    assert '"processor_payment_method_ref": None' in source


def test_no_scheduled_job_collects_against_a_stored_card() -> None:
    source = inspect.getsource(scheduled_jobs)
    assert "charge_saved_method" not in source
    assert "collect_due_invoices" not in source.replace(
        "# billing.collect_due_invoices was here", ""
    )
    # The scheduler has no reason to hold a payment service at all now.
    assert "PaymentService" not in source


def test_the_two_ways_money_arrives_both_have_a_person() -> None:
    """Checkout, and a bank transfer an administrator confirms receiving."""
    assert hasattr(service.PaymentService, "start_invoice_payment")
    assert hasattr(service.PaymentService, "confirm_manual_transfer")
    confirm = inspect.getsource(service.PaymentService.confirm_manual_transfer)
    assert "confirmed_by_user_id" in confirm


def test_a_learners_month_keeps_nothing_about_the_card() -> None:
    """/me Phase 4. The individual band holds no instrument either."""
    from nevo.db.models.me import MePurchase
    from nevo.me import billing as me_billing

    columns = {column.name for column in MePurchase.__table__.columns}
    for forbidden in ("authorization", "card", "last4", "customer_code", "token", "bin"):
        assert not any(forbidden in name for name in columns), (forbidden, columns)
    source = inspect.getsource(me_billing)
    assert "authorization_code" not in source
    assert "authorization.reusable" not in source
    assert "charge_authorization" not in source


def test_a_learners_checkout_arms_on_its_own_flag_not_the_key() -> None:
    from nevo.api import me_billing as me_billing_api

    source = inspect.getsource(me_billing_api.me_checkout)
    assert source.index("me_billing_enabled") < source.index("configured")
