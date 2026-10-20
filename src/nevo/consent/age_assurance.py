"""DOB reconciliation: adults resolve discrepancies before learning can resume."""

from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import aliased

from nevo.db.models.account import Class, StudentClassEnrollment, User
from nevo.db.models.consent_assurance import AgeCheck
from nevo.db.models.frontend_support import Notification
from nevo.domain.accounts.age_bands import (
    age_on,
    band_for_age,
    band_for_date_of_birth,
    band_for_year_group,
)
from nevo.domain.accounts.vocabulary import UserRole, UserStatus
from nevo.domain.consent.vocabulary import AgeCheckState


def discrepancy_exceeds_two_years(first: date, second: date) -> bool:
    earlier, later = sorted((first, second))
    if earlier.year > 9997:
        return False
    try:
        anniversary = earlier.replace(year=earlier.year + 2)
    except ValueError:
        anniversary = earlier.replace(year=earlier.year + 2, day=28)
    return later > anniversary


async def age_check_blocks(session, student_id) -> bool:
    return bool(
        await session.scalar(
            select(AgeCheck.id).where(
                AgeCheck.student_id == student_id, AgeCheck.state == AgeCheckState.MISMATCH
            )
        )
    )


async def capture_band(session, check, today):
    years = await session.scalars(
        select(Class.year_group)
        .join(StudentClassEnrollment, StudentClassEnrollment.class_id == Class.id)
        .where(
            StudentClassEnrollment.student_id == check.student_id,
            Class.school_id == check.school_id,
        )
    )
    bands = {band_for_year_group(year) for year in years}
    check.enrolled_age_band = (
        next(iter(bands)).value if len(bands) == 1 and None not in bands else None
    )
    check.band_checked_on = today


def blocking_reasons(check):
    school, parent = check.school_date_of_birth, check.parent_date_of_birth
    reasons = []
    if school is None or parent is None:
        reasons.append("date_missing")
    if check.enrolled_age_band is None:
        reasons.append("enrolled_age_band_unavailable")
    today = check.band_checked_on
    if school and parent:
        if discrepancy_exceeds_two_years(school, parent):
            reasons.append("date_gap_exceeds_two_years")
        if today and check.enrolled_age_band:
            if any(
                age_on(born, today) < 0
                or band_for_age(age_on(born, today)).value != check.enrolled_age_band
                for born in (school, parent)
            ):
                reasons.append("outside_enrolled_age_band")
    return reasons


async def notify_school(session, check, now):
    """The deletion clock starts only when a durable school inbox notice exists."""
    if check.school_notified_at is not None:
        return
    recipients = list(
        await session.scalars(
            select(User).where(
                User.school_id == check.school_id,
                User.role.in_([UserRole.SENCO_ADMIN, UserRole.OTHER_ADMIN]),
                User.status == UserStatus.ACTIVE,
            )
        )
    )
    for actor in recipients:
        session.add(
            Notification(
                recipient_id=actor.id,
                recipient_role=actor.role.value,
                type="consent_action_required",
                category="consent",
                title="Please recheck a pupil's date of birth",
                description=(
                    "A pupil's account is on hold while the school and parent recheck "
                    "the date of birth. Unresolved roster records are removed 30 days "
                    "after this notice. No identity document is needed."
                ),
                navigates_to=f"/admin/students/{check.student_id}",
                created_at=now,
            )
        )
    if recipients:
        check.school_notified_at = now


async def apply_check(session, check, student, now, *, parent_actor=None):
    reasons = blocking_reasons(check)
    dates_match = (
        check.school_date_of_birth is not None
        and check.school_date_of_birth == check.parent_date_of_birth
    )
    reconfirmed = (
        check.school_rechecked_at is not None
        and check.parent_reconfirmed_at is not None
        and check.parent_reconfirmed_at >= check.school_rechecked_at
    )
    # Once held, even agreeing corrected dates require both adults' fresh checks.
    can_confirm = not reasons and (
        reconfirmed
        or (
            dates_match
            and check.school_notified_at is None
            and check.state is not AgeCheckState.MISMATCH
        )
    )
    check.resolved_at = check.resolved_by_user_id = None
    check.agreed_date_of_birth = None
    if can_confirm:
        check.agreed_date_of_birth = check.parent_date_of_birth
        if reconfirmed:
            check.state = AgeCheckState.RESOLVED
            check.resolved_at = now
            check.resolved_by_user_id = parent_actor or check.parent_reconfirmed_by
            check.resolution_note = (
                "School rechecked; parent reconfirmed. Parent date is operative."
            )
        else:
            check.state = AgeCheckState.MATCHED
        student.date_of_birth = check.parent_date_of_birth
    else:
        check.state = AgeCheckState.MISMATCH
        if not reconfirmed:
            reasons.append("reconfirmation_required")
        await notify_school(session, check, now)
        dates = [born for born in (check.school_date_of_birth, check.parent_date_of_birth) if born]
        student.date_of_birth = max(dates) if dates else None
    student.age_band = band_for_date_of_birth(student.date_of_birth, now.date())
    check.hold_reasons = reasons
    check.updated_at = now
    await session.flush()
    # Recompute the purpose/deletion deadline after the age-check trigger has run.
    await session.refresh(student)


async def record_parent_date(session, *, school_id, student_id, born, now):
    student = await session.get(User, student_id, with_for_update=True)
    check = await session.scalar(
        select(AgeCheck).where(AgeCheck.student_id == student_id).with_for_update()
    )
    if check is None:
        check = AgeCheck(
            school_id=school_id,
            student_id=student_id,
            school_date_of_birth=student.date_of_birth,
            state=AgeCheckState.AWAITING_PARENT,
        )
        session.add(check)
        await capture_band(session, check, now.date())
    if check.state is AgeCheckState.MISMATCH:
        # Consent resubmission is not the explicit reconfirmation workflow.
        check.parent_reconfirmed_at = check.parent_reconfirmed_by = None
    elif (
        check.state in {AgeCheckState.MATCHED, AgeCheckState.RESOLVED}
        and born != check.parent_date_of_birth
    ):
        check.school_notified_at = None
        check.school_rechecked_at = check.parent_reconfirmed_at = None
        check.school_rechecked_by = check.parent_reconfirmed_by = None
        check.state = AgeCheckState.MISMATCH
    check.parent_date_of_birth = born
    await apply_check(session, check, student, now)
    return check.state


async def reconcile_school_date(session, student_id, school_date_of_birth):
    student = await session.get(User, student_id, with_for_update=True)
    check = await session.scalar(
        select(AgeCheck).where(AgeCheck.student_id == student_id).with_for_update()
    )
    if check is None:
        return
    if check.school_date_of_birth == school_date_of_birth:
        if check.agreed_date_of_birth and not check.blocks_access:
            student.date_of_birth = check.agreed_date_of_birth
            student.age_band = band_for_date_of_birth(check.agreed_date_of_birth)
        return
    if not check.blocks_access and school_date_of_birth != check.school_date_of_birth:
        check.school_notified_at = None
    check.school_date_of_birth = school_date_of_birth
    check.school_rechecked_at = check.parent_reconfirmed_at = None
    check.school_rechecked_by = check.parent_reconfirmed_by = None
    await capture_band(session, check, datetime.now(UTC).date())
    check.state = AgeCheckState.MISMATCH
    await apply_check(session, check, student, datetime.now(UTC))


async def prepare_pending_holds(sessions, now):
    """Notify backfilled mismatches and retain the original deadline on retries."""
    async with sessions.begin() as session:
        administrator = aliased(User)
        students = list(
            await session.scalars(
                select(User)
                .join(AgeCheck, AgeCheck.student_id == User.id)
                .where(
                    AgeCheck.state == AgeCheckState.MISMATCH,
                    AgeCheck.school_notified_at.is_(None),
                    select(administrator.id)
                    .where(
                        administrator.school_id == User.school_id,
                        administrator.role.in_([UserRole.SENCO_ADMIN, UserRole.OTHER_ADMIN]),
                        administrator.status == UserStatus.ACTIVE,
                    )
                    .exists(),
                )
                .with_for_update(of=User, skip_locked=True)
                .limit(200)
            )
        )
        for student in students:
            check = await session.scalar(
                select(AgeCheck).where(AgeCheck.student_id == student.id).with_for_update()
            )
            await capture_band(session, check, now.date())
            await apply_check(session, check, student, now)
