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


def test_upgrade_renders_profile_channel_dimensions() -> None:
    sql = render_sql("upgrade", "head")

    assert "create type channel_preference_strength" in sql
    assert "visual_spatial_preference" in sql
    assert "auditory_preference" in sql
    assert "reading_writing_preference" in sql
    assert "interactive_kinesthetic_preference" in sql
    assert "calculation_complete" in sql


def test_downgrade_removes_profile_channel_dimensions() -> None:
    sql = render_sql("downgrade", "20260706_0010:20260705_0009")

    assert "drop column interactive_kinesthetic_preference" in sql
    assert "drop column visual_spatial_preference" in sql
    assert "drop type channel_preference_strength" in sql
