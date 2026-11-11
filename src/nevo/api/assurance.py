"""What a core-function check can read after a deploy.

Yinka, 11 November: a check runs against production after every deploy and a
failure stops the next one. Two of its chains need something from the server.

    Backups exist, a restore has been proven, and the purge runs when it
    should.

    The safety check fails closed.

Three of those four are things this process can see. The fourth is not, and
saying so is the point of this module rather than a gap in it: Supabase holds
the backups and nothing in the application can list them, so "a restore has
been proven" is an operational fact a person establishes, not a measurement.
It is read from BACKUP_RESTORE_VERIFIED_AT and goes stale, so an unprovable
claim becomes a tracked one that fails the check when nobody has proven it
lately.

Carries counts and dates only - no child, no school, no identifier - so it can
be read by a deploy check without a credential, the way /health is.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Request
from sqlalchemy import func, select

from nevo.api.dependencies import DatabaseSession
from nevo.db.models.account import User
from nevo.db.models.retention import LearnerPurgeReceipt
from nevo.db.models.safety import ContentSafetyEvent
from nevo.db.models.scheduled_job import ScheduledJobRun

router = APIRouter(tags=["system"])

#: The purge sweep runs hourly, so a day without one is a fault rather than a
#: quiet night. Generous on purpose: this gate stops deploys, and a flaky gate
#: gets switched off.
PURGE_STALE_AFTER_HOURS = 26

#: How long a proven restore counts for. A quarter is the usual audit answer
#: and matches how often anybody will actually do one.
RESTORE_PROOF_VALID_DAYS = 90

#: The job that anonymises a learner once their retention date passes.
PURGE_JOB = "retention.anonymise"

#: What the runner writes when a job finishes without raising. Taken from
#: ops/jobs.py rather than assumed: this check first asked for "ok", which no
#: job has ever written, so a healthy purge read as a failure against the live
#: database.
JOB_SUCCEEDED = "succeeded"


def _age_hours(moment: datetime | None, now: datetime) -> float | None:
    return None if moment is None else (now - moment).total_seconds() / 3600


async def _purge(session: DatabaseSession, now: datetime) -> dict[str, object]:
    """Whether the purge is running, and whether anything has been missed.

    Two separate questions. A job that ran is not the same as a job that did
    its work, so the second figure is children whose retention date has
    passed and who have not been purged - which is the thing the register
    actually promises.
    """
    run = await session.scalar(select(ScheduledJobRun).where(ScheduledJobRun.job_name == PURGE_JOB))
    overdue = await session.scalar(
        select(func.count(User.id)).where(
            User.retention_due_at.is_not(None),
            User.retention_due_at < now,
            User.retention_purged_at.is_(None),
        )
    )
    receipts = await session.scalar(select(func.count(LearnerPurgeReceipt.id)))
    age = _age_hours(run.last_finished_at if run else None, now)
    ran_recently = age is not None and age <= PURGE_STALE_AFTER_HOURS
    return {
        "job": PURGE_JOB,
        "lastFinishedAt": run.last_finished_at.isoformat() if run and run.last_finished_at else "",
        "lastStatus": run.last_status if run else "never_run",
        "runCount": run.run_count if run else 0,
        "hoursSinceLastRun": round(age, 1) if age is not None else None,
        "overdueNotPurged": int(overdue or 0),
        "receiptsTotal": int(receipts or 0),
        "ok": bool(ran_recently and run and run.last_status == JOB_SUCCEEDED and not overdue),
    }


def _backups(now: datetime) -> dict[str, object]:
    """The one thing here that is a claim rather than a measurement.

    Supabase holds the backups and the application cannot list them, so this
    reads the date somebody last proved a restore. Unset reads as not ok,
    which is correct: an unproven backup is not a backup.
    """
    raw = (os.environ.get("BACKUP_RESTORE_VERIFIED_AT") or "").strip()
    verified: datetime | None = None
    if raw:
        try:
            verified = datetime.fromisoformat(raw)
        except ValueError:
            verified = None
        if verified is not None and verified.tzinfo is None:
            verified = verified.replace(tzinfo=UTC)
    age_days = None if verified is None else (now - verified).days
    return {
        "restoreVerifiedAt": verified.isoformat() if verified else "",
        "restoreProofAgeDays": age_days,
        "validForDays": RESTORE_PROOF_VALID_DAYS,
        # Deliberately not inferred from anything. Nothing in here can see a
        # backup, so a green light would be a guess dressed as a check.
        "measurable": False,
        "ok": bool(
            verified is not None
            and verified <= now
            and now - verified <= timedelta(days=RESTORE_PROOF_VALID_DAYS)
        ),
        "note": (
            "Set BACKUP_RESTORE_VERIFIED_AT to the date a restore was last "
            "proven. The application cannot see the backups themselves."
        )
        if raw == ""
        else "",
    }


async def _safety(request: Request, session: DatabaseSession) -> dict[str, object]:
    """Whether a refusal is what happens when the check cannot run.

    Fails closed by construction: the guard raises rather than returning when
    it has no key, when the material is too long, and when the provider
    answers anything it cannot read. There is no path that allows content
    through unchecked, which is the invariant the deploy gate wants - and it
    is held by a test rather than by this endpoint, because a process cannot
    honestly certify its own code. What is reported here is whether the guard
    is configured and that it has been deciding things.
    """
    gateway = getattr(request.app.state, "ai_gateway", None)
    guard = getattr(gateway, "safety", None) if gateway else None
    configured = bool(getattr(guard, "configured", False))
    decided = await session.scalar(select(func.count(ContentSafetyEvent.id)))
    blocked = await session.scalar(
        select(func.count(ContentSafetyEvent.id)).where(ContentSafetyEvent.action != "allow")
    )
    return {
        "configured": configured,
        "failsClosedWhenUnconfigured": True,
        "decisionsRecorded": int(decided or 0),
        "nonAllowDecisions": int(blocked or 0),
        "ok": configured,
    }


@router.get("/health/assurance")
async def assurance(request: Request, session: DatabaseSession) -> dict[str, object]:
    """Counts and dates a deploy check can assert on. No identifiers."""
    now = datetime.now(UTC)
    purge = await _purge(session, now)
    backups = _backups(now)
    safety = await _safety(request, session)
    return {
        "checkedAt": now.isoformat(),
        "purge": purge,
        "backups": backups,
        "safety": safety,
        # One field for a gate to read, and the parts beside it so a failure
        # says which chain broke without a second request.
        "ok": bool(purge["ok"] and backups["ok"] and safety["ok"]),
    }
