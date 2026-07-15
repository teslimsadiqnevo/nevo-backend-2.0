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


def test_upgrade_renders_attention_flag_schema() -> None:
    sql = render_sql("upgrade", "head")

    assert "create type attention_flag_type" in sql
    assert "engagement_decline" in sql
    assert "sudden_change" in sql
    assert "create table attention_flags" in sql
    assert "create table escalations" in sql
    assert "create table intervention_recommendations" in sql
    assert "ai_gateway_call_id" in sql
    assert "intervention_recommendation.default" in sql
    assert '{{"recommendation_text"' in sql


def test_downgrade_removes_attention_flag_schema() -> None:
    sql = render_sql("downgrade", "20260708_0012:20260707_0011")

    assert "delete from ai_prompt_templates" in sql
    assert "drop table intervention_recommendations" in sql
    assert "drop table escalations" in sql
    assert "drop table attention_flags" in sql
    assert "drop type attention_flag_type" in sql
