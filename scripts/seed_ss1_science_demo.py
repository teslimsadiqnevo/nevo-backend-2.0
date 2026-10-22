"""Create five synthetic, consent-confirmed pupils; do not fabricate onboarding."""

import asyncio
from datetime import UTC, date, datetime
from uuid import UUID

from seed_e2e_probe_student import database_url
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from nevo.api.product_auth import credential_hasher
from nevo.db.models.account import Class, ConsentRecord, School, StudentClassEnrollment, User
from nevo.db.models.permission import Admin
from nevo.domain.accounts.age_bands import band_for_date_of_birth
from nevo.domain.accounts.vocabulary import AuthMethod, ConsentStatus, UserRole, UserStatus
from nevo.domain.consent.vocabulary import REQUIRED_LEARNING_CONSENT

FIXTURE = "ss1-science-demo-20261022"


async def main() -> None:
    engine = create_async_engine(database_url())
    try:
        async with async_sessionmaker(engine, expire_on_commit=False).begin() as session:
            school = await session.get(School, UUID("c5cd0a8d-043c-4f97-aad2-4a724a877a29"))
            school_class = await session.get(Class, UUID("c2c33ea2-9d48-41dd-b259-62511686bcc3"))
            if (
                school is None
                or not school.name.startswith("E2E Test Academy")
                or school_class is None
                or school_class.school_id != school.id
                or school_class.name != "SS 1 Science"
            ):
                raise RuntimeError("Expected synthetic test school/class not found")
            admin = await session.scalar(select(Admin).where(Admin.school_id == school.id))
            if admin is None:
                raise RuntimeError("Test school administrator missing")
            born = date(2010, 6, 1)
            for index, name in enumerate(("Amina", "Bayo", "Chidi", "Dara", "Efe"), 1):
                login = f"NV-SS1SCI{index:02d}"
                existing = await session.scalar(select(User).where(User.login_identifier == login))
                if existing is not None:
                    if (
                        existing.school_id != school.id
                        or existing.preferences.get("testFixture") != FIXTURE
                    ):
                        raise RuntimeError("Refusing to overwrite a non-fixture identity")
                    continue
                student = User(
                    school_id=school.id,
                    role=UserRole.STUDENT,
                    auth_method=AuthMethod.PIN,
                    first_name=name,
                    last_name="Demo",
                    admission_number=f"E2E/SCI{index:02d}",
                    login_identifier=login,
                    date_of_birth=born,
                    age_band=band_for_date_of_birth(born),
                    pin_hash=credential_hasher().hash_pin("4820"),
                    status=UserStatus.ACTIVE,
                    preferences={"testFixture": FIXTURE},
                )
                session.add(student)
                await session.flush()
                session.add(StudentClassEnrollment(student_id=student.id, class_id=school_class.id))
                now = datetime.now(UTC)
                session.add(
                    ConsentRecord(
                        subject_user_id=student.id,
                        consent_type=REQUIRED_LEARNING_CONSENT,
                        status=ConsentStatus.CONFIRMED,
                        confirmation_source="school",
                        confirmed_by_admin_id=admin.user_id,
                        confirmed_at=now,
                        confirmed_via="email",
                        notice_version="synthetic-test-fixture",
                        last_changed_at=now,
                        last_channel="test_fixture",
                    )
                )
            await session.flush()
            students = list(
                await session.scalars(
                    select(User)
                    .where(
                        User.school_id == school.id,
                        User.login_identifier.in_([f"NV-SS1SCI{i:02d}" for i in range(1, 6)]),
                    )
                    .order_by(User.login_identifier)
                )
            )
            if len(students) != 5:
                raise RuntimeError("Fixture verification failed")
            for student in students:
                print(
                    f"{student.first_name} Demo | {student.login_identifier} | "
                    f"{student.admission_number}"
                )
            print(
                f"Verified five synthetic pupils; school code {school.school_code}; "
                "onboarding untouched"
            )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
