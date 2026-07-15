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


def test_upgrade_renders_post_lesson_profile_update_schema() -> None:
    sql = render_sql("upgrade", "head")

    assert "create type profile_attention_flag_status" in sql
    assert "create table learner_profile_attention_flags" in sql
    assert "ix_learner_profile_attention_flags_student_created" in sql
    assert "ix_learner_profile_attention_flags_status_created" in sql
    assert "profile_update.default" in sql
    assert '{{"updates":[{{"dimension":"cognitive_load_threshold"' in sql


def test_downgrade_removes_post_lesson_profile_update_schema() -> None:
    sql = render_sql("downgrade", "20260707_0011:20260706_0010")

    assert "delete from ai_prompt_templates" in sql
    assert "drop table learner_profile_attention_flags" in sql
    assert "drop type profile_attention_flag_status" in sql
