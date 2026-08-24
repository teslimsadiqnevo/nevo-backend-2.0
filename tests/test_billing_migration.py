import os
import subprocess
import sys


def render_sql(*arguments: str) -> str:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = (
        "postgresql+asyncpg://postgres:postgres@localhost:5432/nevo"
    )
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *arguments, "--sql"],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
    return result.stdout.casefold()


def test_upgrade_renders_billing_schema() -> None:
    sql = render_sql("upgrade", "head")

    assert "create type subscription_tier" in sql
    assert "create type invoice_status" in sql
    assert "create type payment_method_type" in sql
    assert "create table billing_contacts" in sql
    assert "create table billing_payment_methods" in sql
    assert "create table invoices" in sql
    assert "create table subscription_tiers" in sql
    assert "create table exchange_rates" in sql
    assert "create table contracts" in sql
    assert "create table step_up_schedules" in sql
    assert "create table billing_ledger" in sql
    assert "add column subscription_tier" in sql
    assert "add column billing_contact_id" in sql
    assert "add column payment_source" in sql
    assert "25000" in sql
    assert "50000" in sql
    assert "80000" in sql
    assert "140000" in sql
    assert "vat_amount_usd" in sql


def test_downgrade_removes_billing_schema() -> None:
    sql = render_sql("downgrade", "20260822_0020:20260812_0019")

    assert "drop table invoices" in sql
    assert "drop table billing_payment_methods" in sql
    assert "drop table billing_contacts" in sql
    assert "drop column subscription_tier" in sql
    assert "drop type subscription_tier" in sql


def test_downgrade_removes_billing_architecture_schema() -> None:
    sql = render_sql("downgrade", "20260824_0026:20260822_0025")

    assert "drop table billing_ledger" in sql
    assert "drop table step_up_schedules" in sql
    assert "drop table contracts" in sql
    assert "drop table exchange_rates" in sql
    assert "drop table subscription_tiers" in sql
    assert "drop column payment_source" in sql
    assert "drop type payment_source" in sql
    assert "drop type pricing_currency" in sql
