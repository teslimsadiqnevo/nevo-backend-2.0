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


def test_upgrade_renders_ai_gateway_schema_and_seed_prompts() -> None:
    sql = render_sql("upgrade", "head")

    assert "create table ai_prompt_templates" in sql
    assert "create table ai_gateway_calls" in sql
    assert "adaptation.default" in sql
    assert "lesson_generation.default" in sql
    assert "narrative.default" in sql


def test_downgrade_removes_ai_gateway_schema() -> None:
    sql = render_sql("downgrade", "20260704_0007:20260704_0006")

    assert "drop table ai_gateway_calls" in sql
    assert "drop table ai_prompt_templates" in sql
