"""What a core-function check reads after a deploy.

Yinka, 11 November: a check runs against production after every deploy and a
failure stops the next one. Two chains need something from the server - that
the purge runs when it should and a restore has been proven, and that the
safety check fails closed.

Three of those four this process can see. "A restore has been proven" it
cannot: Supabase holds the backups and nothing in the application can list
them. So that one is read from a date somebody sets after proving a restore,
and it goes stale - an unprovable claim becomes a tracked one that fails the
gate when nobody has proven it lately. Reporting it as measurable would be a
guess dressed as a check.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nevo.api.assurance import RESTORE_PROOF_VALID_DAYS, router
from nevo.api.dependencies import database_session


class FakeScalars:
    """Answers the handful of scalar queries the endpoint makes, in order."""

    def __init__(self, answers: list) -> None:
        self.answers = list(answers)

    async def scalar(self, *_args, **_kwargs):
        return self.answers.pop(0) if self.answers else 0


@pytest.fixture
def client():
    def build(answers):
        app = FastAPI()
        app.include_router(router)
        app.state.ai_gateway = None
        app.dependency_overrides[database_session] = lambda: FakeScalars(answers)
        return TestClient(app)

    return build


def _answers(*, run=None, overdue=0, receipts=0, decided=0, blocked=0):
    # Order matters: the endpoint asks for the job run, the overdue count,
    # the receipts, then the two safety counts.
    return [run, overdue, receipts, decided, blocked]


class Run:
    def __init__(self, finished_at, status="succeeded", count=5) -> None:
        self.last_finished_at = finished_at
        self.last_status = status
        self.run_count = count


def test_a_healthy_purge_reads_ok(client, monkeypatch) -> None:
    monkeypatch.setenv(
        "BACKUP_RESTORE_VERIFIED_AT", (datetime.now(UTC) - timedelta(days=3)).isoformat()
    )
    body = (
        client(_answers(run=Run(datetime.now(UTC) - timedelta(hours=1))))
        .get("/health/assurance")
        .json()
    )

    assert body["purge"]["ok"] is True
    assert body["purge"]["overdueNotPurged"] == 0
    assert body["backups"]["ok"] is True


def test_a_purge_that_has_never_run_is_not_ok(client) -> None:
    body = client(_answers(run=None)).get("/health/assurance").json()
    assert body["purge"]["lastStatus"] == "never_run"
    assert body["purge"]["ok"] is False
    assert body["ok"] is False


def test_a_stale_purge_is_not_ok(client) -> None:
    """It runs hourly, so a day without one is a fault, not a quiet night."""
    body = (
        client(_answers(run=Run(datetime.now(UTC) - timedelta(hours=48))))
        .get("/health/assurance")
        .json()
    )
    assert body["purge"]["ok"] is False
    assert body["purge"]["hoursSinceLastRun"] > 26


def test_a_job_that_ran_but_missed_a_child_is_not_ok(client) -> None:
    """A job that ran is not the same as a job that did its work.

    This is the figure the register actually promises: nobody is past their
    retention date and still holding data.
    """
    body = (
        client(_answers(run=Run(datetime.now(UTC) - timedelta(hours=1)), overdue=2))
        .get("/health/assurance")
        .json()
    )

    assert body["purge"]["overdueNotPurged"] == 2
    assert body["purge"]["ok"] is False


def test_a_failed_purge_run_is_not_ok(client) -> None:
    body = (
        client(_answers(run=Run(datetime.now(UTC) - timedelta(hours=1), status="error")))
        .get("/health/assurance")
        .json()
    )
    assert body["purge"]["ok"] is False


# --- backups ----------------------------------------------------------------


def test_an_unset_restore_date_is_not_ok_and_says_what_to_do(client, monkeypatch) -> None:
    """An unproven backup is not a backup."""
    monkeypatch.delenv("BACKUP_RESTORE_VERIFIED_AT", raising=False)
    body = client(_answers()).get("/health/assurance").json()

    assert body["backups"]["ok"] is False
    assert body["backups"]["restoreVerifiedAt"] == ""
    assert "BACKUP_RESTORE_VERIFIED_AT" in body["backups"]["note"]


def test_a_stale_restore_proof_is_not_ok(client, monkeypatch) -> None:
    old = datetime.now(UTC) - timedelta(days=RESTORE_PROOF_VALID_DAYS + 1)
    monkeypatch.setenv("BACKUP_RESTORE_VERIFIED_AT", old.isoformat())
    body = client(_answers()).get("/health/assurance").json()

    assert body["backups"]["ok"] is False
    assert body["backups"]["restoreProofAgeDays"] > RESTORE_PROOF_VALID_DAYS


def test_an_unreadable_restore_date_is_not_ok(client, monkeypatch) -> None:
    monkeypatch.setenv("BACKUP_RESTORE_VERIFIED_AT", "last Tuesday")
    body = client(_answers()).get("/health/assurance").json()
    assert body["backups"]["ok"] is False


def test_a_restore_date_in_the_future_is_not_ok(client, monkeypatch) -> None:
    monkeypatch.setenv(
        "BACKUP_RESTORE_VERIFIED_AT", (datetime.now(UTC) + timedelta(days=5)).isoformat()
    )
    assert client(_answers()).get("/health/assurance").json()["backups"]["ok"] is False


def test_a_date_without_a_timezone_is_read_as_utc(client, monkeypatch) -> None:
    monkeypatch.setenv("BACKUP_RESTORE_VERIFIED_AT", "2026-11-01T09:00:00")
    assert client(_answers()).get("/health/assurance").json()["backups"]["ok"] is True


def test_backups_never_claim_to_be_measured(client, monkeypatch) -> None:
    """The honest part. Nothing here can see a backup."""
    monkeypatch.setenv("BACKUP_RESTORE_VERIFIED_AT", datetime.now(UTC).isoformat())
    assert client(_answers()).get("/health/assurance").json()["backups"]["measurable"] is False


# --- safety -----------------------------------------------------------------


def test_safety_with_no_gateway_is_not_ok(client) -> None:
    body = client(_answers()).get("/health/assurance").json()
    assert body["safety"]["configured"] is False
    assert body["safety"]["ok"] is False


def test_fails_closed_is_an_invariant_of_the_guard_not_a_report() -> None:
    """Asserted against the guard itself: a process cannot certify its own code.

    check() raises rather than returning when it has no key, so there is no
    path that lets content through unchecked. That is the property the gate
    wants, and it belongs in a test.
    """
    import asyncio

    from nevo.ai_gateway.safety import ContentSafetyGuard, SafetyUnavailable

    guard = ContentSafetyGuard(api_key=None, base_url="https://example.invalid", model="m")
    assert guard.configured is False
    with pytest.raises(SafetyUnavailable):
        asyncio.run(guard.check("anything at all", phase="lesson_source"))


# --- the payload itself -----------------------------------------------------


def test_one_field_a_gate_can_read(client, monkeypatch) -> None:
    monkeypatch.setenv("BACKUP_RESTORE_VERIFIED_AT", datetime.now(UTC).isoformat())
    body = client(_answers(run=Run(datetime.now(UTC)))).get("/health/assurance").json()
    assert set(body) == {"checkedAt", "purge", "backups", "safety", "ok"}
    # Each chain beside it, so a red gate says which one broke.
    assert body["ok"] is (body["purge"]["ok"] and body["backups"]["ok"] and body["safety"]["ok"])


def test_it_carries_no_identifiers(client) -> None:
    """It is read without a credential, like /health."""
    body = (
        client(_answers(run=Run(datetime.now(UTC)), overdue=3, receipts=9))
        .get("/health/assurance")
        .text
    )
    for leak in ("student", "school", "email", "@", "name"):
        assert leak not in body.casefold(), f"{leak} appeared in the payload"
