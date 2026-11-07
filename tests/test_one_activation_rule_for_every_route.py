"""A child activates when their school is covered by a current invoice.

Lydia's ruling of 7 November. The rule lives at the point of activation
rather than on each route, because a rule that lives in one path gets
bypassed by the other two - adding one child checked an invoice, while a
bulk class upload and a child setting their own PIN from an invite did not,
so children piled onto rosters a school had stopped paying for.

Deliberately not "paid". Paid before active punishes a child for the
bursar's timing and would stop a whole school starting on day one: at the
start of a term the invoice exists and is not yet due, so nothing is
blocked. What it prevents is a roster growing on an unpaid account.
"""

from __future__ import annotations

import inspect

from nevo.api import onboarding, product_admin, product_auth
from nevo.api.product_common import covered_by_a_current_invoice


def test_all_three_routes_ask_the_same_question() -> None:
    for module in (product_admin, onboarding, product_auth):
        assert "covered_by_a_current_invoice" in inspect.getsource(module), module.__name__


def test_the_rule_is_overdue_not_unpaid() -> None:
    source = inspect.getsource(covered_by_a_current_invoice)
    # An invoice that exists and is not yet due does not block anybody, so a
    # school's first day of term works normally.
    assert "due_at < today" in source
    assert "InvoiceStatus.PAID" in source
    # Nothing waits for paid_at: that would hold a child up for the bursar.
    assert "paid_at" not in source


def test_a_school_with_no_invoice_is_not_blocked() -> None:
    # Nothing has been billed yet, so there is nothing for a child to be
    # outside of. Without this a brand new school could enrol nobody.
    source = inspect.getsource(covered_by_a_current_invoice)
    assert "if not invoices:" in source
    assert "return True" in source


def test_the_import_asks_once_for_the_whole_upload() -> None:
    # One invoice state covers every row, and asking per row would be a
    # query per child.
    source = inspect.getsource(onboarding)
    assert "may_start = await covered_by_a_current_invoice(session, school.id)" in source
    assert "may_start=may_start" in source


def test_a_teacher_from_an_import_is_still_invited_not_active() -> None:
    # The rule is about children. A teacher arrives invited either way,
    # because an invitation is how a teacher sets a password.
    source = inspect.getsource(onboarding._create_person)
    assert "else UserStatus.INVITED" in source
    assert "if is_student" in source
