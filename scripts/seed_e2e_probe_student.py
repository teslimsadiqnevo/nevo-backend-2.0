"""The one student CI signs in as, with a handle that never changes.

Everything else in the E2E tenant is generated, so its identifiers move every
time it is rebuilt - which is correct for data meant to exercise thresholds,
and useless for a test that has to sign in as somebody. This is the fixed
point: one child, one handle, written down in docs/test-tenant-spec.md and
safe to put in CI. Ask B66.

Idempotent. Run it after seed_e2e_tenant.py, or on its own against an
existing tenant.

Usage:
    .venv/bin/python scripts/seed_e2e_probe_student.py
"""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, date, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from nevo.api.product_auth import credential_hasher
from nevo.db.models.account import (
    Class,
    ConsentRecord,
    School,
    StudentClassEnrollment,
    User,
)
from nevo.db.models.permission import Admin
from nevo.domain.accounts.age_bands import band_for_date_of_birth
from nevo.domain.accounts.vocabulary import (
    AuthMethod,
    ConsentStatus,
    UserRole,
    UserStatus,
)
from nevo.domain.consent.vocabulary import REQUIRED_LEARNING_CONSENT

#: The handle CI signs in with. Fixed by agreement, not generated.
LOGIN_IDENTIFIER = "NV-E2E000"
ADMISSION_NUMBER = "E2E/PROBE"
PIN = "4820"
BORN = date(2014, 9, 1)

#: Consent is given, so the probe student can actually reach a lesson. A
#: child the tests cannot get past the consent gate is a child the tests
#: cannot use.
CONSENT = ConsentStatus.CONFIRMED


def database_url() -> str:
    for line in Path(".env").read_text().splitlines():
        match = re.match(r"\s*DATABASE_URL\s*=\s*(.+)", line)
        if match:
            raw = match.group(1).strip().strip('"').strip("'")
            raw = raw.replace("postgresql://", "postgresql+asyncpg://")
            return re.sub(r"[?&]sslmode=\w+", "", raw)
    raise SystemExit("DATABASE_URL not found in .env")


async def main() -> None:
    engine = create_async_engine(database_url())
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker.begin() as session:
        school = await session.scalar(select(School).where(School.name.ilike("E2E Test Academy%")))
        if school is None:
            raise SystemExit("No E2E tenant. Run seed_e2e_tenant.py first.")
        existing = await session.scalar(
            select(User).where(User.login_identifier == LOGIN_IDENTIFIER)
        )
        if existing is not None:
            print(f"already present: {LOGIN_IDENTIFIER} in {school.school_code}")
            return
        school_class = await session.scalar(
            select(Class)
            .where(Class.school_id == school.id, Class.archived_at.is_(None))
            .order_by(Class.name)
        )
        student = User(
            school_id=school.id,
            role=UserRole.STUDENT,
            auth_method=AuthMethod.PIN,
            first_name="Probe",
            last_name="Student",
            admission_number=ADMISSION_NUMBER,
            login_identifier=LOGIN_IDENTIFIER,
            date_of_birth=BORN,
            age_band=band_for_date_of_birth(BORN),
            pin_hash=credential_hasher().hash_pin(PIN),
            status=UserStatus.ACTIVE,
        )
        session.add(student)
        await session.flush()
        if school_class is not None:
            session.add(StudentClassEnrollment(student_id=student.id, class_id=school_class.id))
        now = datetime.now(UTC)
        # The table insists a school confirmation names the administrator who
        # made it, which is the point of recording one at all.
        admin = await session.scalar(
            select(Admin).where(Admin.school_id == school.id).order_by(Admin.id)
        )
        if admin is None:
            raise SystemExit("No administrator on the E2E tenant to confirm consent.")
        session.add(
            ConsentRecord(
                subject_user_id=student.id,
                consent_type=REQUIRED_LEARNING_CONSENT,
                status=CONSENT,
                confirmation_source="school",
                # The admin's *user* id. The column is named admin_id and
                # its foreign key points at users, which is a trap worth
                # knowing about before it costs somebody an afternoon.
                confirmed_by_admin_id=admin.user_id,
                confirmed_at=now,
                confirmed_via="email",
                last_changed_at=now,
                last_channel="email",
            )
        )
        print(f"schoolCode={school.school_code}")
        print(f"loginIdentifier={LOGIN_IDENTIFIER}")
        print(f"admissionNumber={ADMISSION_NUMBER}")
        print(f"pin={PIN}")
        print(f"class={school_class.name if school_class else 'none'}")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
