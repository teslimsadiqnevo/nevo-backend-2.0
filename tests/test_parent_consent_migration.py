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


def test_upgrade_renders_parent_consent_schema_and_roster_trigger() -> None:
    sql = render_sql("upgrade", "head")

    assert "create table parent_links" in sql
    assert "create table consent_invitations" in sql
    assert "create table consent_notification_outbox" in sql
    assert "parent_guardian" in sql
    assert "create_pending_consent_for_roster_student" in sql
    assert "trg_users_roster_student_pending_consent" in sql


def test_downgrade_removes_parent_consent_schema() -> None:
    sql = render_sql("downgrade", "20260704_0006:20260703_0005")

    assert "drop table parent_links" in sql
    assert "drop table consent_invitations" in sql
    assert "drop table consent_notification_outbox" in sql
    assert (
        "drop function if exists create_pending_consent_for_roster_student"
        in sql
    )
    assert "where confirmation_source = 'parent'" in sql
