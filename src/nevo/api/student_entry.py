"""A child follows their school's link, and Nevo already knows who they are.

The entry flow asked a child to type back what the roster already held: their
name, and their age. That is collecting personal data twice, the second time
from the person least able to consent to it, and it is the reason this is a
server-side resolution rather than a screen.

The consent gate is here too, and it is the API's rather than the routing's. A
child whose parent has not consented cannot start the assessment, cannot reach
a lesson and cannot finish setting up an account, whatever URL they open.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime, timedelta
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from nevo.api.age_checks import age_check_blocks
from nevo.api.auth import AuthServiceDependency, SessionResponse, StudentPin, client_ip
from nevo.api.casing import CAMEL_CONFIG
from nevo.api.dependencies import DatabaseSession
from nevo.api.response_models import CamelResponse
from nevo.db.models.account import (
    Class,
    ConsentRecord,
    School,
    StudentClassEnrollment,
    User,
)
from nevo.db.models.auth import AuthLoginAttempt
from nevo.db.models.product import StudentOnboardingGrant
from nevo.domain.accounts.vocabulary import AuthMethod, ConsentStatus, UserRole, UserStatus
from nevo.domain.consent.vocabulary import REQUIRED_LEARNING_CONSENT

router = APIRouter(prefix="/api/v1/student-entry", tags=["learning product"])


class StudentEntryState(CamelResponse):
    """What the link resolves to.

    A first name, a class, and which of two states the child is in. Nothing
    else: the refusal a waiting child sees carries no more about them than
    the state itself.
    """

    #: The child's own name, from the roster. Never typed by the child.
    first_name: str
    class_name: str | None
    consent_state: Literal["given", "pending"]
    #: Derived from the date of birth on the roster, never asked for and never
    #: stored twice. Null where the roster has no date of birth, which the
    #: import is supposed to have refused.
    age: int | None
    #: True once the child has a PIN and can sign in normally.
    account_ready: bool
    #: True while the school and the parent disagree about the child's date
    #: of birth. The child cannot start, and there is nothing for them to do
    #: about it, so the screen says the school is checking something.
    age_check_pending: bool = False


class PinChoice(BaseModel):
    model_config = CAMEL_CONFIG

    #: The same shape the sign-in doors check, shared rather than restated:
    #: a PIN that can be chosen here and refused there is a lockout.
    pin: StudentPin


class StudentEntrySession(CamelResponse):
    user_id: UUID
    login_identifier: str | None
    session: SessionResponse
    pin_length: Literal[4] = 4


def age_on(born: date | None, today: date | None = None) -> int | None:
    """Whole years, the way a person counts them."""

    if born is None:
        return None
    now = today or datetime.now(UTC).date()
    return now.year - born.year - ((now.month, now.day) < (born.month, born.day))


async def _grant(session: AsyncSession, token: str) -> StudentOnboardingGrant:
    digest = hashlib.sha256(token.encode()).hexdigest()
    grant = await session.scalar(
        select(StudentOnboardingGrant).where(
            StudentOnboardingGrant.token_digest == digest,
            StudentOnboardingGrant.expires_at > datetime.now(UTC),
        )
    )
    if grant is None or grant.student_id is None:
        # A link that names no child is the old flow's link, and the old flow
        # asked the child who they were. There is nothing to resolve.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "entry_link_invalid",
                "message": "Ask your teacher for a new link.",
            },
        )
    return grant


async def _student(session: AsyncSession, grant: StudentOnboardingGrant) -> User:
    student = await session.get(User, grant.student_id)
    if student is None or student.role is not UserRole.STUDENT:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "entry_link_invalid",
                "message": "Ask your teacher for a new link.",
            },
        )
    return student


async def _has_consent(session: AsyncSession, student_id: UUID) -> bool:
    status_value = await session.scalar(
        select(ConsentRecord.status).where(
            ConsentRecord.subject_user_id == student_id,
            ConsentRecord.consent_type == REQUIRED_LEARNING_CONSENT,
        )
    )
    return status_value is ConsentStatus.CONFIRMED


async def _class_name(session: AsyncSession, grant: StudentOnboardingGrant) -> str | None:
    school_class = await session.get(Class, grant.class_id)
    return school_class.name if school_class else None


async def _state(session: AsyncSession, grant: StudentOnboardingGrant) -> StudentEntryState:
    student = await _student(session, grant)
    return StudentEntryState(
        first_name=student.first_name or "",
        class_name=await _class_name(session, grant),
        consent_state="given" if await _has_consent(session, student.id) else "pending",
        age_check_pending=await age_check_blocks(session, student.id),
        age=age_on(student.date_of_birth),
        account_ready=student.pin_hash is not None,
    )


@router.get("/{token}", response_model=StudentEntryState)
async def resolve_entry_link(token: str, session: DatabaseSession) -> StudentEntryState:
    """Who this link belongs to, and whether they can start.

    Unauthenticated: the child has no account yet, and the link is the
    credential. It returns their own first name rather than asking for it.
    """

    grant = await _grant(session, token)
    return await _state(session, grant)


@router.post("/{token}/pin", response_model=StudentEntrySession)
async def set_pin_and_start(
    token: str,
    payload: PinChoice,
    response: Response,
    session: DatabaseSession,
    auth_service: AuthServiceDependency,
) -> StudentEntrySession:
    """Set a PIN and begin, if the child's parent has consented.

    Refused here rather than by routing. A direct URL is a route, and a gate
    a route can walk around is not a gate.
    """

    from nevo.api.product_auth import credential_hasher

    grant = await _grant(session, token)
    student = await _student(session, grant)
    if await age_check_blocks(session, student.id):
        # Two sources disagree about how old this child is, so nobody is sure
        # they should be offered the product. A person settles that with the
        # school and the parent; it is never resolved by asking the child.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "age_check_pending",
                "message": (
                    "Nevo is checking something with your school. "
                    "Open this link again in a day or two."
                ),
            },
        )
    if not await _has_consent(session, student.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "consent_pending",
                # Nothing about the child, to a screen anyone with the link
                # can open. Only the state.
                "message": (
                    "Nevo is waiting for a grown-up at home to say yes. "
                    "Come back and open this link again once they have."
                ),
            },
        )
    if student.login_identifier is None:
        import secrets

        student.login_identifier = f"NV-{secrets.token_hex(3).upper()}"
    student.pin_hash = credential_hasher().hash_pin(payload.pin)
    student.auth_method = AuthMethod.PIN
    student.status = UserStatus.ACTIVE
    enrolled = await session.scalar(
        select(StudentClassEnrollment.id).where(
            StudentClassEnrollment.student_id == student.id,
            StudentClassEnrollment.class_id == grant.class_id,
        )
    )
    if enrolled is None:
        session.add(StudentClassEnrollment(student_id=student.id, class_id=grant.class_id))
    # The link keeps working: a child who loses their PIN opens it again, and
    # a link marked used at the first PIN is a child locked out by a typo.
    await session.commit()
    issued = await auth_service.issue_for_provisioned_user(student.id)
    response.headers["Cache-Control"] = "no-store"
    return StudentEntrySession(
        user_id=student.id,
        login_identifier=student.login_identifier,
        session=SessionResponse.from_issued(issued),
    )


#: Five wrong guesses in fifteen minutes, the same rule the sign-in doors use.
#: This endpoint is unauthenticated with a four-character school code in front
#: of it, so without this it is an enumeration tool for a children's roster.
LOOKUP_MAX_ATTEMPTS = 5
LOOKUP_WINDOW = timedelta(minutes=15)

#: Misses against one school code before that code is held, whoever is asking.
#:
#: The backstop, and the only one of the three buckets nothing in the caller's
#: control can dodge: an IP bucket is spoofable through X-Forwarded-For and an
#: identity bucket is sidestepped by guessing a different ID each time, which
#: is exactly what enumerating a roster looks like. Set high enough that a
#: classroom of children mistyping on their first morning never reaches it -
#: sixty in a quarter of an hour - and far below the thousands of guesses
#: reading a roster out of this would take.
LOOKUP_MAX_PER_SCHOOL = 60

#: Said for every miss, whatever the miss was. It never says which field was
#: wrong and never reveals whether an ID exists: SCRUM-208, and the reason is
#: that a child's identifier is not a thing to confirm to a stranger.
NO_MATCH = {
    "code": "entry_not_found",
    "message": "That did not match. Check the code and the ID with your teacher.",
}


class StudentEntryLookup(BaseModel):
    """What a child types on 05 Entry: the school's code, then their own ID."""

    model_config = CAMEL_CONFIG

    #: Four characters on the screen, but not validated to four here - an
    #: older school whose code predates SCRUM-201 must still be able to sign
    #: its children in.
    school_code: str = Field(min_length=2, max_length=50)
    admission_number: str = Field(min_length=1, max_length=60)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


async def _misses(session: AsyncSession, cutoff: datetime, *digests: str) -> int:
    found = await session.scalar(
        select(func.count())
        .select_from(AuthLoginAttempt)
        .where(
            AuthLoginAttempt.succeeded.is_(False),
            AuthLoginAttempt.occurred_at >= cutoff,
            or_(
                AuthLoginAttempt.identity_digest.in_(digests),
                AuthLoginAttempt.ip_digest.in_(digests),
            ),
        )
    )
    return found or 0


def _too_many() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail={
            "code": "too_many_attempts",
            "message": "Too many tries. Wait a few minutes and try again.",
        },
    )


async def _throttle(session: AsyncSession, identity: str, ip: str, school: str) -> None:
    """Three buckets, because no one of them holds on its own.

    This child, from this address, against this school. The first two are
    cheap to dodge - a new ID each guess, or a rotated X-Forwarded-For - and
    the third is the one that actually stops a roster being read out.
    """

    cutoff = datetime.now(UTC) - LOOKUP_WINDOW
    if await _misses(session, cutoff, identity, ip) >= LOOKUP_MAX_ATTEMPTS:
        raise _too_many()
    if await _misses(session, cutoff, school) >= LOOKUP_MAX_PER_SCHOOL:
        raise _too_many()


async def _record(
    session: AsyncSession, identity: str, ip: str, school: str, *, succeeded: bool
) -> None:
    now = datetime.now(UTC)
    session.add(
        AuthLoginAttempt(
            identity_digest=identity,
            ip_digest=ip,
            succeeded=succeeded,
            occurred_at=now,
        )
    )
    # A second row carrying only the school bucket. Written on the same table
    # so the whole throttle is one query shape and one retention policy.
    session.add(
        AuthLoginAttempt(
            identity_digest=school,
            ip_digest=school,
            succeeded=succeeded,
            occurred_at=now,
        )
    )
    await session.commit()


@router.post("/lookup", response_model=StudentEntryState)
async def lookup_entry(
    payload: StudentEntryLookup,
    request: Request,
    response: Response,
    session: DatabaseSession,
) -> StudentEntryState:
    """Which child has arrived, from the school's code and their own ID.

    05 Entry's one screen. Unauthenticated, because the child has no account
    yet and this is what identifies them; the school code comes first because
    an admission number is only unique within a school, which is what gives
    the number something to be looked up in. SCRUM-202, SCRUM-208.

    Replaces the entry *link*, which could never resolve: nothing ever wrote
    a grant naming a child, so every token 404'd. There is no link now.

    Nothing is collected. Name, class and date of birth are on the roster
    already and age computes from the date of birth, so the response states
    them rather than asking the child for what the school has told us twice.
    """

    code = payload.school_code.strip().upper()
    admission = payload.admission_number.strip()
    identity = _digest(f"entry:{code.casefold()}:{admission.casefold()}")
    ip = _digest(client_ip(request))
    school = _digest(f"entry-school:{code.casefold()}")
    await _throttle(session, identity, ip, school)
    response.headers["Cache-Control"] = "no-store"
    student = await session.scalar(
        select(User)
        .join(School, School.id == User.school_id)
        .where(
            func.upper(School.school_code) == code,
            User.role == UserRole.STUDENT,
            func.lower(User.admission_number) == admission.casefold(),
            User.status != UserStatus.DEACTIVATED,
        )
        .limit(1)
    )
    if student is None:
        await _record(session, identity, ip, school, succeeded=False)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NO_MATCH)
    await _record(session, identity, ip, school, succeeded=True)
    enrolled_class = await session.scalar(
        select(Class)
        .join(StudentClassEnrollment, StudentClassEnrollment.class_id == Class.id)
        .where(StudentClassEnrollment.student_id == student.id)
        .limit(1)
    )
    # Routed on consent state and on nothing the child did. A child whose
    # parent has not answered gets the waiting screen; when consent arrives
    # the same two fields go straight on by themselves.
    return StudentEntryState(
        first_name=student.first_name or "",
        class_name=enrolled_class.name if enrolled_class else None,
        consent_state="given" if await _has_consent(session, student.id) else "pending",
        age_check_pending=await age_check_blocks(session, student.id),
        age=age_on(student.date_of_birth),
        account_ready=student.pin_hash is not None,
    )
