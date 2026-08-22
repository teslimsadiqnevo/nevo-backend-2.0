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
    assert "add column subscription_tier" in sql
    assert "add column billing_contact_id" in sql


def test_downgrade_removes_billing_schema() -> None:
    sql = render_sql("downgrade", "20260822_0020:20260812_0019")

    assert "drop table invoices" in sql
    assert "drop table billing_payment_methods" in sql
    assert "drop table billing_contacts" in sql
    assert "drop column subscription_tier" in sql
    assert "drop type subscription_tier" in sql
