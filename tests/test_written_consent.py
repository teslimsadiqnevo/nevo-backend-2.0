"""Consent on paper, recorded as the parent's.

A school with four hundred children will not get four hundred email replies.
The paper route exists so those children can learn - and the record it writes
has to identify the parent, which the school-confirmation route never did.
"""

from __future__ import annotations

import pytest

from nevo.consent.written import NOTICE_VERSION, consent_form_lines, render_consent_form
from nevo.db.models.account import ConsentRecord
from nevo.main import app


@pytest.fixture(scope="module")
def spec() -> dict:
    return app.openapi()


def test_the_record_can_say_who_signed_and_what_they_were_shown() -> None:
    columns = {column.name for column in ConsentRecord.__table__.columns}

    # The definition of a consent record: identity, relationship, date,
    # method, and the version of the notice. The last was the easy one to miss.
    assert {
        "parent_name_on_form",
        "parent_relationship",
        "signed_on",
        "notice_version",
        "confirmed_via",
    } <= columns


def test_who_uploaded_the_form_is_kept_apart_from_who_consented() -> None:
    columns = {column.name for column in ConsentRecord.__table__.columns}

    assert {"uploaded_by_user_id", "uploaded_at", "evidence_storage_path"} <= columns


def test_the_database_refuses_written_consent_that_names_nobody() -> None:
    constraints = {constraint.name for constraint in ConsentRecord.__table__.constraints}

    assert "ck_consent_records_written_consent_identifies_the_parent" in constraints


def test_the_form_carries_the_cross_border_transfer_as_its_own_permission() -> None:
    lines = consent_form_lines(school_name="Sunrise Academy")
    text = "\n".join(lines)

    # A school's own generic slip does not mention processing outside Nigeria,
    # which is the reason Nevo supplies the form at all.
    assert "SEPARATE PERMISSION" in text
    assert "outside" in text
    assert "Anthropic" in text and "OpenAI" in text and "YarnGPT" in text


def test_the_form_names_the_notice_version_a_parent_signed_against() -> None:
    assert NOTICE_VERSION in "\n".join(consent_form_lines(school_name="Sunrise Academy"))


def test_the_form_says_withdrawal_is_no_harder_than_consenting() -> None:
    text = "\n".join(consent_form_lines(school_name="Sunrise Academy"))

    assert "withdraw" in text


def test_the_form_is_a_pdf_a_school_can_print() -> None:
    assert render_consent_form(school_name="Sunrise Academy").startswith(b"%PDF")


def test_a_school_can_download_the_form_and_upload_a_signed_one(spec: dict) -> None:
    assert "get" in spec["paths"]["/api/v1/consents/form"]
    assert "post" in spec["paths"]["/api/v1/students/{student_id}/consents/written"]


def test_the_response_says_whether_the_parent_was_told(spec: dict) -> None:
    fields = spec["components"]["schemas"]["WrittenConsentResponse"]["properties"]

    # A parent who signed on paper and is never told has no route to withdraw.
    assert "parentNotified" in fields
    assert {"parentName", "parentRelationship", "signedOn", "noticeVersion"} <= set(fields)
