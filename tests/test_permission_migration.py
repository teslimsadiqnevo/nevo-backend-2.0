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


def test_upgrade_renders_permission_schema() -> None:
    sql = render_migration("upgrade", "head")

    assert "create type permission_scope" in sql
    assert "create table admins" in sql
    assert "create table admin_scope_assignments" in sql
    assert "create table admin_invitations" in sql
    assert "uq_admin_scope_assignments_active" in sql


def test_downgrade_removes_permission_schema() -> None:
    sql = render_migration("downgrade", "20260703_0004:20260702_0003")

    assert "drop table admin_invitations" in sql
    assert "drop table admin_scope_assignments" in sql
    assert "drop table admins" in sql
    assert "drop type permission_scope" in sql
