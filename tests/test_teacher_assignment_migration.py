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


def test_upgrade_renders_teacher_assignment_schema() -> None:
    sql = render_migration("upgrade", "head")

    assert "create type teacher_assignment_role" in sql
    assert "create type teacher_assignment_source" in sql
    assert "create table teacher_class_assignments" in sql
    assert "uq_teacher_class_assignments_active_primary" in sql
    assert "uq_teacher_class_assignments_active_pair" in sql


def test_downgrade_removes_teacher_assignment_schema() -> None:
    sql = render_migration("downgrade", "20260703_0005:20260703_0004")

    assert "drop table teacher_class_assignments" in sql
    assert "drop type teacher_assignment_source" in sql
    assert "drop type teacher_assignment_role" in sql
