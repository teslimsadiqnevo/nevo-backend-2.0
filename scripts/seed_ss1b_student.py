"""Seed one onboarded student into SS 1B at the E2E school.

Onboarded means every gate a lesson checks is already satisfied: the
account is active, a consent record is confirmed, the four onboarding
modules are marked complete, and the child is enrolled in the class. A
student missing any one of them is refused at the door with a 409 and
looks, from the console, like a broken lesson.

Shaped from Ada and Tunde, the two children already in SS 1B, so this one
behaves the same way rather than differently for reasons nobody recorded.

Deliberately not fabricated: no probe scores, no subject placements, no
mastery. The profile says it is a fixture and says what was not measured,
because a seeded score that looks measured is worse than an empty one.

Idempotent. The ids are derived from the admission number, so running it
twice updates rather than duplicates.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from nevo.api.product_auth import credential_hasher
from nevo.db.models.account import (
    ConsentRecord,
    StudentClassEnrollment,
    User,
)
from nevo.domain.accounts.vocabulary import (
    ConsentMethod,
    ConsentStatus,
    ConsentType,
    UserRole,
    UserStatus,
)
from nevo.domain.consent.vocabulary import ConsentConfirmationSource
from nevo.intelligence.learning_runtime import ONBOARDING_MODULES

CLASS_ID = uuid.UUID("c0976688-e822-4709-9e33-59d81f5c0a56")  # SS 1B
SCHOOL_ID = uuid.UUID("c5cd0a8d-043c-4f97-aad2-4a724a877a29")  # E2E Test Academy
ADMIN_ID = uuid.UUID("5ec65d60-5f32-4bfb-8168-b9588a46b288")  # E2E Admin

FIRST_NAME = os.environ.get("SEED_FIRST_NAME", "Chidi")
ADMISSION = os.environ.get("SEED_ADMISSION", "E2E/SS1B/003")
LOGIN = os.environ.get("SEED_LOGIN", "NV-E2E-SS1B-003")
PIN = os.environ.get("SEED_PIN", "4821")
BORN = date(2011, 5, 9)

#: Derived from the admission number so a second run is an update.
STUDENT_ID = uuid.uuid5(uuid.NAMESPACE_URL, f"nevo:student:{ADMISSION}")


def _baseline(now: datetime) -> dict:
    return {
        "version": 1,
        "age_band": "senior_secondary",
        "seeded_at": now.isoformat(),
        "updated_at": now.isoformat(),
        "confidence": "low",
        "feature_count": 0,
        "measurements": {},
        "motor_baselines": {},
        "motor_step_skipped": False,
        "motor_latency_status": "uncorrected_no_baseline",
        "completed_modules": list(ONBOARDING_MODULES),
        "onboarding_completed_at": now.isoformat(),
        "seeded_fixture": True,
        "seeded_reason": (
            "Seeded SS 1B fixture: onboarding marked complete so lessons can be "
            "started. No probe scores, subject placements or mastery fabricated."
        ),
    }


async def main() -> None:
    url = os.environ["DATABASE_URL"]
    engine = create_async_engine(url, connect_args={"statement_cache_size": 0})
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(UTC)
    try:
        async with sessions.begin() as session:
            student = await session.get(User, STUDENT_ID)
            if student is None:
                student = User(id=STUDENT_ID, school_id=SCHOOL_ID, role=UserRole.STUDENT)
                session.add(student)
            student.first_name = FIRST_NAME
            student.last_name = "E2E"
            student.status = UserStatus.ACTIVE
            student.auth_method = "pin"
            student.login_identifier = LOGIN
            student.admission_number = ADMISSION
            student.age_band = "senior_secondary"
            student.date_of_birth = BORN
            student.pin_hash = credential_hasher().hash_pin(PIN)
            student.baseline_profile = _baseline(now)
            await session.flush()

            enrolled = await session.scalar(
                select(StudentClassEnrollment).where(
                    StudentClassEnrollment.student_id == STUDENT_ID,
                    StudentClassEnrollment.class_id == CLASS_ID,
                )
            )
            if enrolled is None:
                session.add(
                    StudentClassEnrollment(student_id=STUDENT_ID, class_id=CLASS_ID)
                )

            # The gate a lesson actually checks. Recorded as the school
            # confirming it, which is what the other two in this class have,
            # and never as a parent: no parent agreed to anything here.
            consent = await session.scalar(
                select(ConsentRecord).where(
                    ConsentRecord.subject_user_id == STUDENT_ID,
                    ConsentRecord.consent_type == ConsentType.DATA_PROCESSING,
                )
            )
            if consent is None:
                consent = ConsentRecord(
                    subject_user_id=STUDENT_ID,
                    consent_type=ConsentType.DATA_PROCESSING,
                )
                session.add(consent)
            consent.status = ConsentStatus.CONFIRMED
            consent.confirmation_source = ConsentConfirmationSource.SCHOOL
            consent.confirmed_by_admin_id = ADMIN_ID
            consent.confirmed_by_parent_id = None
            consent.confirmed_via = ConsentMethod.EMAIL
            consent.confirmed_at = now
            consent.last_actor_user_id = ADMIN_ID
            consent.last_changed_at = now

        async with sessions() as session:
            check = await session.get(User, STUDENT_ID)
            modules = set((check.baseline_profile or {}).get("completed_modules") or ())
            status = await session.scalar(
                select(ConsentRecord.status).where(
                    ConsentRecord.subject_user_id == STUDENT_ID,
                    ConsentRecord.consent_type == ConsentType.DATA_PROCESSING,
                )
            )
            print(f"student      {check.first_name} {check.last_name}  {check.id}")
            print(f"sign in      {check.login_identifier} / admission {check.admission_number}")
            print(f"pin          {PIN}")
            print(f"status       {check.status}")
            print(f"consent      {status}")
            print(f"onboarding   {len(modules & set(ONBOARDING_MODULES))}/{len(ONBOARDING_MODULES)} modules")
            ok = (
                check.status is UserStatus.ACTIVE
                and status is ConsentStatus.CONFIRMED
                and modules >= set(ONBOARDING_MODULES)
            )
            print("ready" if ok else "NOT READY")
            sys.exit(0 if ok else 1)
    finally:
        await engine.dispose()


asyncio.run(main())
