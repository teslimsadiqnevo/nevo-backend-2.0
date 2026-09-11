"""Signing a parent in with a code sent to the contact their school holds.

No password. A parent has one thing we can prove: the email address or phone
number the school entered when it asked for consent. A code sent there and
typed back is the whole of the authentication, which puts the weight on the
controls around it rather than on the secret's length.

A four-digit code is ten thousand combinations, so all four of these matter:
the code is single-use, it expires quickly, a code dies after a handful of
wrong guesses, and asking for a new one kills the old. Without the attempt
cap in particular, four digits would be guessable in an afternoon.
"""
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nevo.db.models.auth import ParentLoginCode

CODE_LIFETIME = timedelta(minutes=10)
MAX_ATTEMPTS = 5
"""Wrong guesses a single code survives. Five of ten thousand is a 1-in-2000
chance per code, and a new code has to be requested to try again."""

MAX_LIVE_CODES_PER_HOUR = 5
"""Requests for one contact per hour, so the attempt cap cannot be sidestepped
by asking for code after code."""


@dataclass(frozen=True, slots=True)
class IssuedCode:
    """What was sent, and to whom.

    ``code`` is returned so the caller can deliver it, and is never stored.
    ``parent_user_id`` is None when the contact matches nobody - the caller
    still answers as though it sent something.
    """

    code: str | None
    parent_user_id: UUID | None
    expires_at: datetime


class ParentLoginCodes:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        pepper: str,
        code_length: int = 4,
    ) -> None:
        self._sessions = sessions
        self._pepper = pepper.encode()
        self._code_length = code_length

    def digest(self, contact: str, code: str) -> str:
        """Peppered, and bound to the contact.

        Binding it means a digest lifted from the table cannot be replayed
        against a different parent.
        """
        return hmac.new(
            self._pepper,
            f"parent-code:{normalise(contact)}:{code}".encode(),
            hashlib.sha256,
        ).hexdigest()

    async def issue(
        self,
        *,
        contact: str,
        parent_user_id: UUID | None,
        now: datetime | None = None,
    ) -> IssuedCode:
        """Mint a code for a contact, standing down any earlier one."""
        moment = now or datetime.now(UTC)
        expires_at = moment + CODE_LIFETIME
        normalised = normalise(contact)
        async with self._sessions.begin() as session:
            recent = list(
                await session.scalars(
                    select(ParentLoginCode).where(
                        ParentLoginCode.contact == normalised,
                        ParentLoginCode.created_at > moment - timedelta(hours=1),
                    )
                )
            )
            if len(recent) >= MAX_LIVE_CODES_PER_HOUR:
                # Answer as though a code went out. Saying "too many requests"
                # here would confirm the address is one we know.
                return IssuedCode(
                    code=None,
                    parent_user_id=parent_user_id,
                    expires_at=expires_at,
                )
            for stale in recent:
                # Asking for a new code retires the old one, so an attacker
                # cannot keep a pile of live codes and guess one each.
                stale.consumed_at = stale.consumed_at or moment
            code = "".join(secrets.choice("0123456789") for _ in range(self._code_length))
            session.add(
                ParentLoginCode(
                    contact=normalised,
                    code_digest=self.digest(normalised, code),
                    parent_user_id=parent_user_id,
                    expires_at=expires_at,
                )
            )
        return IssuedCode(
            code=code,
            parent_user_id=parent_user_id,
            expires_at=expires_at,
        )

    async def redeem(
        self,
        *,
        contact: str,
        code: str,
        now: datetime | None = None,
    ) -> UUID | None:
        """Spend a code. Returns the parent it belongs to, or None.

        Every failure counts against the code, including one that names a
        contact we have never seen, so the timing of a refusal says nothing
        about whether the address is known.
        """
        moment = now or datetime.now(UTC)
        normalised = normalise(contact)
        wanted = self.digest(normalised, code.strip())
        async with self._sessions.begin() as session:
            record = await session.scalar(
                select(ParentLoginCode)
                .where(
                    ParentLoginCode.contact == normalised,
                    ParentLoginCode.consumed_at.is_(None),
                )
                .order_by(ParentLoginCode.created_at.desc())
                .limit(1)
                .with_for_update()
            )
            if record is None or record.expires_at <= moment:
                return None
            record.attempt_count += 1
            if record.attempt_count > MAX_ATTEMPTS:
                record.consumed_at = moment
                return None
            if not hmac.compare_digest(record.code_digest, wanted):
                return None
            record.consumed_at = moment
            return record.parent_user_id


def normalise(contact: str) -> str:
    """One spelling of a contact, so a code follows it wherever it is typed."""
    return " ".join(contact.split()).strip().casefold()
