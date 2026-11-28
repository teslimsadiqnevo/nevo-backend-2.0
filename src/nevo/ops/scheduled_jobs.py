import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nevo.billing.issuance import InvoiceIssuanceService, queue_billing_emails
from nevo.consent.expiry import ConsentExpiryService
from nevo.content_parsing.service import ContentParsingService
from nevo.db.models.billing import Invoice
from nevo.db.models.safety import ContentSafetyEvent
from nevo.db.models.sso import SchoolSsoConfiguration
from nevo.domain.accounts.vocabulary import SsoConnectionStatus
from nevo.domain.billing.vocabulary import InvoiceStatus
from nevo.notifications.digests import send_attention_digests
from nevo.ops.jobs import ScheduledJob
from nevo.retention.service import RetentionService
from nevo.scheduler.service import FsrsSchedulerService
from nevo.sso.service import SsoService

logger = logging.getLogger(__name__)

DAILY = timedelta(hours=24)
WEEKLY = timedelta(days=7)
HOURLY = timedelta(hours=1)


async def expire_safety_review_text_rows(
    sessions: async_sessionmaker[AsyncSession], *, now: datetime | None = None
) -> int:
    """Erase expired flagged material while retaining the decision audit."""
    cutoff = now or datetime.now(UTC)
    async with sessions.begin() as session:
        result = await session.execute(
            update(ContentSafetyEvent)
            .where(
                ContentSafetyEvent.material_expires_at <= cutoff,
                ContentSafetyEvent.review_material.is_not(None),
            )
            .values(review_material=None)
        )
    return result.rowcount or 0


def build_scheduled_jobs(
    *,
    sessions: async_sessionmaker[AsyncSession],
    retention_service: RetentionService,
    scheduler_service: FsrsSchedulerService,
    sso_service: SsoService,
    issuance_service: InvoiceIssuanceService,
    content_parsing_service: ContentParsingService,
    email_delivery: object | None = None,
) -> tuple[ScheduledJob, ...]:
    """The recurring work that used to require someone to press a button."""

    async def me_renewal_reminders() -> str:
        from nevo.me.reminders import send_renewal_reminders

        return await send_renewal_reminders(sessions, email_delivery)

    async def me_double_payment_alerts() -> str:
        from nevo.me.billing import alert_double_payments

        return await alert_double_payments(sessions, email_delivery)

    async def issue_invoices() -> str:
        return (await issuance_service.issue_due_invoices()).summary()

    async def invoice_reminders() -> str:
        today = datetime.now(UTC).date()
        queued = 0
        async with sessions.begin() as session:
            invoices = list(
                await session.scalars(
                    select(Invoice).where(
                        Invoice.status == InvoiceStatus.PENDING,
                    )
                )
            )
            for invoice in invoices:
                queued += await queue_billing_emails(session, invoice=invoice, kind="issued")
                if invoice.due_at == today or invoice.due_at == today + timedelta(days=7):
                    kind = "reminder_due" if invoice.due_at == today else "reminder_7d"
                    queued += await queue_billing_emails(session, invoice=invoice, kind=kind)
                elif invoice.due_at < today:
                    # SCRUM-310. One reminder once an invoice is past its due
                    # date, and exactly one: queue_billing_emails already
                    # refuses a second of the same kind for the same invoice
                    # and address, so this stays at one however many days the
                    # invoice sits unpaid and however often this job runs.
                    queued += await queue_billing_emails(
                        session, invoice=invoice, kind="reminder_overdue"
                    )
        return f"queued {queued} invoice reminder emails"

    async def attention_digests() -> str:
        return await send_attention_digests(sessions)

    async def retention_sweep() -> str:
        result = await retention_service.sweep()
        if result.failed:
            raise RuntimeError(result.summary())
        return result.summary()

    async def consent_expiry_sweep() -> str:
        return (await ConsentExpiryService(sessions).sweep()).summary()

    async def expire_safety_review_text() -> str:
        count = await expire_safety_review_text_rows(sessions)
        return f"expired {count} safety review texts"

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

    async def close_stale_parse_runs() -> str:
        failed = await content_parsing_service.fail_stale_runs()
        return f"closed {failed} stale parses and uploads"

    async def close_stale_roster_syncs() -> str:
        failed = await sso_service.fail_stale_roster_syncs()
        return f"closed {failed} stale roster syncs"

    # billing.collect_due_invoices was here, and it is gone.
    #
    # It charged each due invoice against the school's stored card, daily,
    # with nobody present. Lydia's rule of 22 November: Nevo stores no
    # reusable payment token for any customer, school or individual, and no
    # path charges a stored instrument with nobody present. Schools pay by
    # invoice and bank transfer, so there is no card to tokenise and nothing
    # for this job to do.
    #
    # It was not idle. It ran 52 times, and on 22 November it attempted two
    # real invoices - 150,500 and 6,450,000 - against a stored token. Nothing
    # was collected and no money moved, but the attempt is the problem. It had
    # skipped itself for months because no payment provider was configured;
    # configuring Paystack on 20 November is what gave it the ability to try.
    #
    # Collection is now a person paying an invoice, which the payment routes
    # already serve.

    return (
        # Weekly by ruling: a flag is a pattern noticed over days, and a
        # message for each one teaches a teacher to ignore the lot.
        ScheduledJob(
            name="attention.weekly_digest",
            interval=WEEKLY,
            run=attention_digests,
        ),
        ScheduledJob(name="retention.anonymise", interval=HOURLY, run=retention_sweep),
        ScheduledJob(name="consent.expire_unanswered", interval=DAILY, run=consent_expiry_sweep),
        ScheduledJob(
            name="safety.expire_review_text", interval=DAILY, run=expire_safety_review_text
        ),
        ScheduledJob(name="scheduler.refresh_due_dates", interval=DAILY, run=refresh_due_dates),
        ScheduledJob(name="sso.roster_sync", interval=DAILY, run=roster_sync),
        ScheduledJob(name="sso.health_probe", interval=HOURLY, run=sso_health_probe),
        ScheduledJob(
            name="content.close_stale_parse_runs",
            interval=timedelta(minutes=5),
            run=close_stale_parse_runs,
        ),
        ScheduledJob(
            name="sso.close_stale_roster_syncs",
            interval=HOURLY,
            run=close_stale_roster_syncs,
        ),
        ScheduledJob(name="billing.issue_invoices", interval=DAILY, run=issue_invoices),
        ScheduledJob(name="billing.invoice_reminders", interval=DAILY, run=invoice_reminders),
        # /me: a reminder before a paid month lapses. Email only; it holds no
        # payment service and cannot charge anyone.
        ScheduledJob(name="me.renewal_reminders", interval=DAILY, run=me_renewal_reminders),
        ScheduledJob(
            name="me.double_payment_alerts", interval=HOURLY, run=me_double_payment_alerts
        ),
    )


async def _connected_sso_schools(
    sessions: async_sessionmaker[AsyncSession],
) -> list[UUID]:
    async with sessions() as session:
        rows = await session.scalars(
            select(SchoolSsoConfiguration.school_id).where(
                SchoolSsoConfiguration.enabled.is_(True),
                SchoolSsoConfiguration.connection_status != SsoConnectionStatus.DISCONNECTED,
            )
        )
    return list(dict.fromkeys(rows.all()))
