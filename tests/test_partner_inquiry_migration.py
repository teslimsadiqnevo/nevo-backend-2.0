import os
import subprocess
import sys


def render_migration(*arguments: str) -> str:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = (
        "postgresql+asyncpg://postgres:postgres@localhost:5432/nevo"
    )
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *arguments, "--sql"],
        check=True,
        capture_output=True,
        env=environment,
        text=True,
    )
    return result.stdout.casefold()


def test_upgrade_renders_partner_inquiry_schema() -> None:
    sql = render_migration("upgrade", "head")

    assert "create type partner_inquiry_role" in sql
    assert "create type partner_inquiry_contact_method" in sql
    assert "create table partner_inquiries" in sql
    assert "ix_partner_inquiries_created_at" in sql


def test_downgrade_removes_partner_inquiry_schema() -> None:
    sql = render_migration(
        "downgrade",
        "20260808_0016:20260711_0015",
    )

    assert "drop table partner_inquiries" in sql
    assert "drop type partner_inquiry_contact_method" in sql
    assert "drop type partner_inquiry_role" in sql
