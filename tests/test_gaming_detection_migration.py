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


def test_upgrade_renders_gaming_detection_schema() -> None:
    sql = render_migration("upgrade", "head")

    assert "create type gaming_suspicion_level" in sql
    assert "create type engagement_anomaly_type" in sql
    assert "create type engagement_anomaly_scope" in sql
    assert "create table learner_engagement_anomalies" in sql
    assert "add column gaming_suspicion_level" in sql
    assert "ix_learner_engagement_anomalies_student_detected" in sql


def test_downgrade_removes_gaming_detection_schema() -> None:
    sql = render_migration("downgrade", "20260812_0018:20260808_0017")

    assert "drop table learner_engagement_anomalies" in sql
    assert "drop column gaming_suspicion_level" in sql
    assert "drop type gaming_suspicion_level" in sql
