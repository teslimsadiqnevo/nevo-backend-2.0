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


def test_upgrade_renders_auth_schema() -> None:
    sql = render_migration("upgrade", "head")

    assert "add column login_identifier" in sql
    assert "create table auth_sessions" in sql
    assert "create table auth_login_attempts" in sql
    assert "create table auth_audit_events" in sql
    assert "uq_auth_sessions_one_active_student" in sql
    assert "uq_users_email_ci" in sql
    assert "uq_users_school_login_identifier_ci" in sql
    assert "role = 'student' and revoked_at is null" in sql


def test_downgrade_removes_auth_schema() -> None:
    sql = render_migration("downgrade", "20260702_0003:20260702_0002")

    assert "drop table auth_audit_events" in sql
    assert "drop table auth_login_attempts" in sql
    assert "drop table auth_sessions" in sql
    assert "drop column login_identifier" in sql
