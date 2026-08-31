import logging
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nevo.billing.issuance import InvoiceIssuanceService
from nevo.db.models.billing import Invoice
from nevo.db.models.sso import SchoolSsoConfiguration
from nevo.domain.accounts.vocabulary import SsoConnectionStatus
from nevo.domain.billing.vocabulary import InvoiceStatus
from nevo.ops.jobs import ScheduledJob
from nevo.payments.errors import PaymentError
from nevo.payments.service import PaymentService
from nevo.retention.service import RetentionService
from nevo.scheduler.service import FsrsSchedulerService
from nevo.sso.service import SsoService

logger = logging.getLogger(__name__)

DAILY = timedelta(hours=24)
HOURLY = timedelta(hours=1)


def build_scheduled_jobs(
    *,
    sessions: async_sessionmaker[AsyncSession],
    retention_service: RetentionService,
    scheduler_service: FsrsSchedulerService,
    sso_service: SsoService,
    payment_service: PaymentService,
    issuance_service: InvoiceIssuanceService,
) -> tuple[ScheduledJob, ...]:
    """The recurring work that used to require someone to press a button."""

    async def issue_invoices() -> str:
        return (await issuance_service.issue_due_invoices()).summary()

    async def retention_sweep() -> str:
        return (await retention_service.sweep()).summary()

    async def refresh_due_dates() -> str:
        refreshed = await scheduler_service.refresh_all_due_dates()
        return f"refreshed {len(refreshed)} concept schedules"

    async def roster_sync() -> str:
        school_ids = await _connected_sso_schools(sessions)
        synced = 0
        failed = 0
        for school_id in school_ids:
            try:
                await sso_service.sync_roster_for_school(
                    school_id=school_id,
                    triggered_by_user_id=None,
                )
            except Exception:
                # A single school's provider outage must not stop the sweep.
                # sync_roster_for_school already records the failed run.
                logger.warning("Scheduled roster sync failed for school %s", school_id)
                failed += 1
            else:
                synced += 1
        return f"synced {synced} schools, {failed} failed"

    async def sso_health_probe() -> str:
        school_ids = await _connected_sso_schools(sessions)
        checked = 0
        for school_id in school_ids:
            try:
                await sso_service.connection_health(school_id)
            except Exception:
                logger.warning("SSO health probe failed for school %s", school_id)
            else:
                checked += 1
        return f"probed {checked} of {len(school_ids)} connections"

    async def collect_due_invoices() -> str:
        if not payment_service.configured:
            return "skipped: no payment provider configured"
        due = await _collectable_invoices(sessions)
        collected = 0
        skipped = 0
        for school_id, invoice_id in due:
            try:
                outcome = await payment_service.charge_saved_method(
                    school_id=school_id,
                    invoice_id=invoice_id,
                )
            except PaymentError:
                skipped += 1
                continue
            except Exception:
                logger.exception("Invoice collection failed for invoice %s", invoice_id)
                skipped += 1
                continue
            if outcome.invoice_paid:
                collected += 1
            else:
                skipped += 1
        return f"collected {collected} invoices, {skipped} not collected"

    return (
        ScheduledJob(name="retention.anonymise", interval=DAILY, run=retention_sweep),
        ScheduledJob(name="scheduler.refresh_due_dates", interval=DAILY, run=refresh_due_dates),
        ScheduledJob(name="sso.roster_sync", interval=DAILY, run=roster_sync),
        ScheduledJob(name="sso.health_probe", interval=HOURLY, run=sso_health_probe),
        # Issuance runs before collection so a freshly raised invoice that is
        # already due is picked up on the same sweep.
        ScheduledJob(name="billing.issue_invoices", interval=DAILY, run=issue_invoices),
        ScheduledJob(
            name="billing.collect_due_invoices",
            interval=DAILY,
            run=collect_due_invoices,
        ),
    )


async def _connected_sso_schools(
    sessions: async_sessionmaker[AsyncSession],
) -> list[UUID]:
    async with sessions() as session:
        rows = await session.scalars(
            select(SchoolSsoConfiguration.school_id).where(
                SchoolSsoConfiguration.enabled.is_(True),
                SchoolSsoConfiguration.connection_status
                != SsoConnectionStatus.DISCONNECTED,
            )
        )
    return list(dict.fromkeys(rows.all()))


async def _collectable_invoices(
    sessions: async_sessionmaker[AsyncSession],
    *,
    today: date | None = None,
) -> list[tuple[UUID, UUID]]:
    """Invoices that are due now and still unpaid."""
    cutoff = today or datetime.now(UTC).date()
    async with sessions() as session:
        rows = await session.execute(
            select(Invoice.school_id, Invoice.id)
            .where(
                Invoice.status.in_((InvoiceStatus.PENDING, InvoiceStatus.OVERDUE)),
                Invoice.due_at <= cutoff,
            )
            .order_by(Invoice.due_at)
            .limit(500)
        )
    return [(school_id, invoice_id) for school_id, invoice_id in rows]
