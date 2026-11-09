"""Durable invoice delivery to each school's billing contacts."""

import asyncio
import logging
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nevo.api.billing import _invoice_working
from nevo.db.models.account import School
from nevo.db.models.billing import BillingEmailDelivery, Invoice
from nevo.intelligence.compliance_audit import render_simple_pdf
from nevo.notifications.branding import render_email
from nevo.notifications.email import ResendEmailDelivery

logger = logging.getLogger(__name__)


class BillingEmailWorker:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], delivery: ResendEmailDelivery):
        self._sessions = sessions
        self._delivery = delivery
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="billing-email-delivery")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task

    async def _run(self) -> None:
        while True:
            try:
                worked = await self.process_next()
            except Exception:
                logger.exception("Billing email worker iteration failed")
                await asyncio.sleep(5)
                continue
            if not worked:
                await asyncio.sleep(5)

    async def process_next(self) -> bool:
        now = datetime.now(UTC)
        async with self._sessions.begin() as session:
            row = await session.scalar(
                select(BillingEmailDelivery)
                .where(
                    BillingEmailDelivery.attempt_count < 6,
                    BillingEmailDelivery.next_attempt_at <= now,
                    or_(
                        BillingEmailDelivery.status == "pending",
                        (BillingEmailDelivery.status == "sending")
                        & (BillingEmailDelivery.next_attempt_at <= now - timedelta(minutes=5)),
                    ),
                )
                .order_by(BillingEmailDelivery.next_attempt_at, BillingEmailDelivery.id)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if row is None:
                return False
            row.status = "sending"
            row.attempt_count += 1
            row.next_attempt_at = now + timedelta(minutes=5)
            delivery_id = row.id
            invoice = await session.get(Invoice, row.invoice_id)
            school = await session.get(School, invoice.school_id) if invoice else None
            recipient, kind = row.email, row.kind
        if invoice is None or school is None:
            await self._finish(delivery_id, "missing invoice or school")
            return True
        if kind != "issued" and invoice.status.value == "paid":
            await self._finish(delivery_id, None)
            return True
        label = "Invoice" if kind == "issued" else "Payment reminder"
        subject = f"Nevo {label.lower()}: {invoice.invoice_number}"
        summary = (
            f"{school.name}: invoice {invoice.invoice_number} for {invoice.period_label}, "
            f"{invoice.currency.value} {invoice.amount:,.2f}, due {invoice.due_at.isoformat()}."
        )
        pdf = render_simple_pdf(
            [
                "NEVO LEARNING INVOICE",
                f"Invoice: {invoice.invoice_number}",
                f"School: {school.name}",
                f"Issued: {invoice.issued_at.isoformat()}",
                f"Due: {invoice.due_at.isoformat()}",
                *_invoice_working(invoice),
                f"Total: {invoice.currency.value} {invoice.amount}",
                f"Status: {invoice.status.value}",
                "This document was generated from the school's billing record.",
            ]
        )
        try:
            await self._delivery.send(
                to=recipient,
                subject=subject,
                text=summary,
                html=render_email(heading=subject, preheader=summary, paragraphs=[summary]),
                attachment=(f"{invoice.invoice_number}.pdf", pdf),
            )
        except Exception as error:
            logger.warning("Billing email delivery failed for %s: %s", delivery_id, error)
            await self._finish(delivery_id, str(error))
        else:
            await self._finish(delivery_id, None)
        return True

    async def _finish(self, delivery_id: UUID, error: str | None) -> None:
        async with self._sessions.begin() as session:
            row = await session.get(BillingEmailDelivery, delivery_id)
            if row is None:
                return
            if error:
                row.status = "failed" if row.attempt_count >= 6 else "pending"
                row.last_error = error[:1000]
                row.next_attempt_at = datetime.now(UTC) + timedelta(
                    minutes=min(60, 2**row.attempt_count)
                )
            else:
                row.status = "sent"
                row.delivered_at = datetime.now(UTC)
                row.last_error = None
