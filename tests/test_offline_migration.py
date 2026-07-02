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


def test_initial_migration_renders_expected_postgresql_contract() -> None:
    sql = render_migration("upgrade", "head")
    assert "create table learner_profiles" in sql
    assert "create table learner_profile_history" in sql
    assert "create type profile_confidence" in sql
    assert "create type processing_channel_preference" in sql
    assert "trg_learner_profile_history_immutable" in sql


def test_rendered_migration_contains_no_prohibited_schema_terms() -> None:
    sql = render_migration("upgrade", "head")

    for prohibited_term in PROHIBITED_SCHEMA_TERMS:
        assert prohibited_term not in sql


def test_initial_migration_has_a_complete_downgrade() -> None:
    sql = render_migration("downgrade", "20260702_0001:base")

    assert "drop table learner_profile_history" in sql
    assert "drop table learner_profiles" in sql
    assert "drop type profile_confidence" in sql
    assert "drop type processing_channel_preference" in sql
