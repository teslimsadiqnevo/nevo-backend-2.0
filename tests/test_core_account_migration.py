import os
import subprocess
import sys

from nevo.domain.learner_profiles.vocabulary import PROHIBITED_SCHEMA_TERMS


def render_migration(*arguments: str) -> str:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = "postgresql+asyncpg://postgres:postgres@localhost:5432/nevo"

    result = subprocess.run(
        [sys.executable, "-m", "alembic", *arguments, "--sql"],
        check=True,
        capture_output=True,
        env=environment,
        text=True,
    )
    return result.stdout.casefold()


def test_upgrade_renders_core_account_tables() -> None:
    sql = render_migration("upgrade", "head")

    for table in (
        "create table schools",
        "create table users",
        "create table classes",
        "create table student_class_enrollments",
        "create table consent_records",
    ):
        assert table in sql

    assert "create type user_role" in sql
    assert "create type consent_confirmed_via" in sql
    # The SCRUM-15 deferred foreign keys are added here.
    assert "fk_learner_profiles_learner_id_users" in sql


def test_rendered_migration_contains_no_prohibited_schema_terms() -> None:
    sql = render_migration("upgrade", "head")

    for prohibited_term in PROHIBITED_SCHEMA_TERMS:
        assert prohibited_term not in sql


def test_downgrade_removes_core_account_tables() -> None:
    sql = render_migration("downgrade", "20260702_0002:20260702_0001")

    assert "drop table consent_records" in sql
    assert "drop table users" in sql
    assert "drop table schools" in sql
    assert "drop type user_role" in sql
