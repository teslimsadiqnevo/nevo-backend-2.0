from sqlalchemy import CheckConstraint, Enum, ForeignKeyConstraint, UniqueConstraint

from nevo.db import models  # noqa: F401
from nevo.db.base import Base


def test_school_carries_subscription_contract_fields() -> None:
    columns = Base.metadata.tables["schools"].columns

    tier = columns["subscription_tier"]
    assert isinstance(tier.type, Enum)
    assert tier.type.enums == ["boutique", "mid_market", "premium", "enterprise"]

    for column in (
        "contract_value",
        "contract_start",
        "contract_end",
        "billing_contact_id",
        "payment_source",
    ):
        assert column in columns

    payment_source = columns["payment_source"]
    assert isinstance(payment_source.type, Enum)
    assert payment_source.type.enums == ["direct", "sterling", "partner"]


def test_billing_contact_is_separate_from_admin_access() -> None:
    table = Base.metadata.tables["billing_contacts"]
    columns = set(table.columns.keys())

    assert {"email", "phone", "address_line1", "city", "country"}.issubset(columns)
    unique_sets = {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert ("school_id",) in unique_sets


def test_payment_method_stores_only_masked_details_and_processor_reference() -> None:
    columns = Base.metadata.tables["billing_payment_methods"].columns

    assert "last_four" in columns
    assert "processor_payment_method_ref" in columns
    for forbidden in (
        "card_number",
        "account_number",
        "cvv",
        "secret",
        "token",
    ):
        assert forbidden not in columns


def test_invoice_schema_matches_admin_history_contract() -> None:
    table = Base.metadata.tables["invoices"]
    columns = set(table.columns.keys())

    assert {
        "invoice_number",
        "school_id",
        "issued_at",
        "amount",
        "status",
        "due_at",
        "paid_at",
        "pdf_url",
    }.issubset(columns)
    status = table.columns["status"]
    assert isinstance(status.type, Enum)
    assert status.type.enums == ["paid", "pending", "overdue"]


def test_billing_architecture_tables_support_dual_currency_contracts() -> None:
    assert {
        "subscription_tiers",
        "exchange_rates",
        "contracts",
        "step_up_schedules",
        "billing_ledger",
    }.issubset(Base.metadata.tables)

    tiers = Base.metadata.tables["subscription_tiers"].columns
    assert {
        "tier_name",
        "min_pupils",
        "max_pupils",
        "founding_partner_usd_rate",
        "commercial_usd_rate",
        "vat_rate",
    }.issubset(tiers.keys())

    contracts = Base.metadata.tables["contracts"].columns
    assert {"school_id", "tier_id", "payment_source", "current_year_index"}.issubset(
        contracts.keys()
    )
    payment_source = contracts["payment_source"]
    assert isinstance(payment_source.type, Enum)
    assert payment_source.type.enums == ["direct", "sterling", "partner"]

    ledger = Base.metadata.tables["billing_ledger"].columns
    assert {
        "amount_usd",
        "applied_discount_percent",
        "net_amount_usd",
        "vat_amount_usd",
        "total_with_vat_usd",
        "billed_currency",
        "fx_rate_applied",
        "total_billed_local",
    }.issubset(ledger.keys())


def test_billing_tables_cascade_by_school_not_by_user() -> None:
    for table_name in ("billing_contacts", "billing_payment_methods", "invoices"):
        table = Base.metadata.tables[table_name]
        for constraint in table.constraints:
            if not isinstance(constraint, ForeignKeyConstraint):
                continue
            for element in constraint.elements:
                if element.column.table.name == "schools":
                    assert element.ondelete == "CASCADE"
                if element.column.table.name == "users":
                    assert element.ondelete == "RESTRICT"


def test_billing_checks_are_present() -> None:
    checks = {
        constraint.name or ""
        for table in Base.metadata.tables.values()
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }

    assert any(name.endswith("contract_value_nonnegative") for name in checks)
    assert any(name.endswith("contract_dates_ordered") for name in checks)
    assert any(name.endswith("last_four_digits") for name in checks)
    assert any(name.endswith("invoice_amount_nonnegative") for name in checks)
