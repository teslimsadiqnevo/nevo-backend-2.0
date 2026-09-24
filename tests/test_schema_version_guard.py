"""A schema behind the code says so, instead of failing at the first write.

A deployment ran for two days with code that writes a column the database did
not have. Every parse got as far as the INSERT, threw, and was discarded. The
service was healthy, the API served the new field in its own schema document,
and the only symptom was that lessons stopped appearing.
"""

from __future__ import annotations

import pytest

from nevo.ops.schema_version import expected_revision, schema_state


class Boom:
    """An engine that cannot be reached."""

    def connect(self):
        raise RuntimeError("no database here")


def test_the_head_is_read_from_the_migration_files() -> None:
    head = expected_revision()

    assert head is not None
    # One head, or None. Two heads is a different problem and this does not
    # pretend to answer it.
    assert head.startswith("2026")


async def test_a_database_it_cannot_reach_is_unknown_not_up_to_date() -> None:
    """The distinction that makes the check worth acting on."""

    state = await schema_state(Boom())  # type: ignore[arg-type]

    assert state["state"] == "unknown"
    assert state["state"] != "up_to_date"


@pytest.mark.parametrize(
    ("applied", "expected_state"),
    [("20260924_0079", "up_to_date"), ("20260921_0073", "behind"), (None, "unknown")],
)
async def test_the_three_answers(applied: str | None, expected_state: str, monkeypatch) -> None:
    from nevo.ops import schema_version

    async def fake_applied(engine: object) -> str | None:
        return applied

    monkeypatch.setattr(schema_version, "applied_revision", fake_applied)
    monkeypatch.setattr(schema_version, "expected_revision", lambda: "20260924_0079")

    state = await schema_version.schema_state(object())  # type: ignore[arg-type]

    assert state["state"] == expected_state


async def test_being_behind_is_logged_as_an_error_with_both_revisions(monkeypatch, caplog) -> None:
    from nevo.ops import schema_version

    async def fake_applied(engine: object) -> str | None:
        return "20260921_0073"

    monkeypatch.setattr(schema_version, "applied_revision", fake_applied)
    monkeypatch.setattr(schema_version, "expected_revision", lambda: "20260924_0079")

    with caplog.at_level("ERROR"):
        await schema_version.warn_if_behind(object())  # type: ignore[arg-type]

    message = caplog.text
    assert "BEHIND" in message
    # Both revisions, so the log line is actionable without another query.
    assert "20260924_0079" in message
    assert "20260921_0073" in message
    assert "alembic upgrade head" in message


def test_health_reports_it() -> None:
    import inspect

    from nevo.main import health

    source = inspect.getsource(health)

    assert '"schema"' in source
    assert "schemaExpected" in source
    assert "schemaApplied" in source
