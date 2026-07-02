from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from nevo.auth.entities import AuthUser
from nevo.auth.errors import (
    InvalidCredentialsError,
    InvalidSessionError,
    RateLimitExceededError,
    SessionExpiredError,
    SessionReplacedError,
)
from nevo.auth.service import AuthService

from .fakes import (
    DeterministicTokenService,
    FakeCredentialHasher,
    MemoryAuditLog,
    MemoryRateLimiter,
    MemorySessionRepository,
    MemoryUserRepository,
)

NOW = datetime(2026, 7, 2, 10, 0, tzinfo=UTC)


@dataclass
class MutableClock:
    value: datetime = NOW

    def __call__(self) -> datetime:
        return self.value


@dataclass
class Harness:
    service: AuthService
    users: MemoryUserRepository
    sessions: MemorySessionRepository
    limiter: MemoryRateLimiter
    audit: MemoryAuditLog
    clock: MutableClock


def auth_user(
    *,
    role: str = "student",
    auth_method: str = "pin",
    status: str = "active",
    email: str | None = None,
    password: str | None = None,
    pin: str | None = "2443",
    login_identifier: str | None = "UZ59R",
    school_auth_method: str | None = "pin",
    deactivated_at: datetime | None = None,
) -> AuthUser:
    return AuthUser(
        id=uuid4(),
        school_id=uuid4(),
        role=role,
        auth_method=auth_method,
        status=status,
        email=email,
        password_hash=f"password:{password}" if password else None,
        pin_hash=f"pin:{pin}" if pin else None,
        login_identifier=login_identifier,
        school_auth_method=school_auth_method,
        deactivated_at=deactivated_at,
    )


def harness_for(*users: AuthUser) -> Harness:
    user_repository = MemoryUserRepository(list(users))
    sessions = MemorySessionRepository()
    limiter = MemoryRateLimiter()
    audit = MemoryAuditLog()
    clock = MutableClock()
    service = AuthService(
        users=user_repository,
        sessions=sessions,
        rate_limiter=limiter,
        audit_log=audit,
        credential_hasher=FakeCredentialHasher(),
        token_service=DeterministicTokenService(),
        now=clock,
    )
    return Harness(service, user_repository, sessions, limiter, audit, clock)


async def password_login(
    harness: Harness,
    *,
    email: str = "teacher@example.com",
    password: str = "valid-password",
):
    return await harness.service.login_with_password(
        email=email,
        password=password,
        ip_address="192.0.2.10",
    )


async def pin_login(
    harness: Harness,
    *,
    school_code: str = "NVS",
    login_identifier: str = "UZ59R",
    pin: str = "2443",
):
    return await harness.service.login_with_pin(
        school_code=school_code,
        login_identifier=login_identifier,
        pin=pin,
        ip_address="192.0.2.11",
    )


async def test_password_login_normalizes_email_and_issues_teacher_session() -> None:
    user = auth_user(
        role="teacher",
        auth_method="email_password",
        email="teacher@example.com",
        password="valid-password",
        pin=None,
        login_identifier=None,
        school_auth_method="email_password",
    )
    harness = harness_for(user)

    issued = await password_login(harness, email=" Teacher@Example.Com ")

    assert issued.user_id == user.id
    assert issued.role == "teacher"
    assert issued.expires_at == NOW + timedelta(minutes=120)
    assert issued.replaced_session is False
    assert harness.limiter.attempts[-1][2] is True
    assert harness.audit.events[-1]["event_type"] == "login_succeeded"


@pytest.mark.parametrize(
    ("status", "deactivated_at", "expected_event"),
    [
        ("invited", None, "deactivated_login_attempt"),
        ("deactivated", NOW, "deactivated_login_attempt"),
    ],
)
async def test_non_active_accounts_receive_generic_login_failure(
    status: str,
    deactivated_at: datetime | None,
    expected_event: str,
) -> None:
    user = auth_user(
        role="teacher",
        auth_method="email_password",
        status=status,
        email="teacher@example.com",
        password="valid-password",
        pin=None,
        login_identifier=None,
        school_auth_method="email_password",
        deactivated_at=deactivated_at,
    )
    harness = harness_for(user)

    with pytest.raises(InvalidCredentialsError):
        await password_login(harness)

    assert harness.limiter.attempts[-1][2] is False
    assert harness.audit.events[-1]["event_type"] == expected_event


async def test_wrong_password_records_failure_without_revealing_account() -> None:
    user = auth_user(
        role="teacher",
        auth_method="email_password",
        email="teacher@example.com",
        password="valid-password",
        pin=None,
        login_identifier=None,
        school_auth_method="email_password",
    )
    harness = harness_for(user)

    with pytest.raises(InvalidCredentialsError):
        await password_login(harness, password="wrong-password")

    assert harness.limiter.attempts[-1][2] is False
    assert harness.audit.events[-1]["event_type"] == "login_failed"


async def test_pin_login_issues_student_session() -> None:
    user = auth_user()
    harness = harness_for(user)

    issued = await pin_login(
        harness,
        school_code=" nVs ",
        login_identifier=" uz59r ",
    )

    assert issued.user_id == user.id
    assert issued.expires_at == NOW + timedelta(minutes=60)
    assert issued.role == "student"


@pytest.mark.parametrize("role", ["teacher", "senco_admin", "other_admin"])
async def test_pin_login_is_restricted_to_students(role: str) -> None:
    user = auth_user(role=role)
    harness = harness_for(user)

    with pytest.raises(InvalidCredentialsError):
        await pin_login(harness)


async def test_sso_account_cannot_use_manual_password_path() -> None:
    user = auth_user(
        role="teacher",
        auth_method="sso",
        email="teacher@example.com",
        password="valid-password",
        pin=None,
        login_identifier=None,
        school_auth_method="sso",
    )
    harness = harness_for(user)

    with pytest.raises(InvalidCredentialsError):
        await password_login(harness)


async def test_second_student_login_replaces_first_session() -> None:
    user = auth_user()
    harness = harness_for(user)
    first = await pin_login(harness)
    second = await pin_login(harness)

    assert second.replaced_session is True
    with pytest.raises(SessionReplacedError) as error:
        await harness.service.authenticate(first.access_token)
    assert (
        error.value.public_message
        == "You logged in on another device, your progress has been saved."
    )

    principal = await harness.service.authenticate(second.access_token)
    assert principal.user_id == user.id
    assert principal.session_id != UUID(int=0)
    assert any(
        event["event_type"] == "session_replaced"
        for event in harness.audit.events
    )


async def test_teacher_can_keep_multiple_active_sessions() -> None:
    user = auth_user(
        role="teacher",
        auth_method="email_password",
        email="teacher@example.com",
        password="valid-password",
        pin=None,
        login_identifier=None,
        school_auth_method="email_password",
    )
    harness = harness_for(user)
    first = await password_login(harness)
    second = await password_login(harness)

    assert second.replaced_session is False
    assert (await harness.service.authenticate(first.access_token)).user_id == user.id
    assert (await harness.service.authenticate(second.access_token)).user_id == user.id


async def test_authenticate_slides_idle_expiry() -> None:
    user = auth_user()
    harness = harness_for(user)
    issued = await pin_login(harness)
    harness.clock.value = NOW + timedelta(minutes=30)

    await harness.service.authenticate(issued.access_token)

    stored = await harness.sessions.find_by_digest(f"digest:{issued.access_token}")
    assert stored is not None
    assert stored.last_seen_at == harness.clock.value
    assert stored.expires_at == harness.clock.value + timedelta(minutes=60)


async def test_expired_session_is_revoked_and_audited() -> None:
    user = auth_user()
    harness = harness_for(user)
    issued = await pin_login(harness)
    harness.clock.value = issued.expires_at

    with pytest.raises(SessionExpiredError):
        await harness.service.authenticate(issued.access_token)

    stored = await harness.sessions.find_by_digest(f"digest:{issued.access_token}")
    assert stored is not None
    assert stored.revocation_reason == "expired"
    assert harness.audit.events[-1]["event_type"] == "session_expired"


async def test_deactivated_user_session_is_invalidated_on_next_request() -> None:
    user = auth_user()
    harness = harness_for(user)
    issued = await pin_login(harness)
    harness.users.users[0] = replace(
        user,
        status="deactivated",
        deactivated_at=NOW,
    )

    with pytest.raises(InvalidSessionError):
        await harness.service.authenticate(issued.access_token)

    stored = await harness.sessions.find_by_digest(f"digest:{issued.access_token}")
    assert stored is not None
    assert stored.revocation_reason == "user_unavailable"


async def test_logout_revokes_session_idempotently() -> None:
    user = auth_user()
    harness = harness_for(user)
    issued = await pin_login(harness)

    await harness.service.logout(issued.access_token)
    await harness.service.logout(issued.access_token)

    with pytest.raises(InvalidSessionError):
        await harness.service.authenticate(issued.access_token)
    assert harness.audit.events[-1]["event_type"] == "logout"


async def test_rate_limited_login_is_rejected_before_credentials() -> None:
    user = auth_user()
    harness = harness_for(user)
    harness.limiter.blocked = True

    with pytest.raises(RateLimitExceededError):
        await pin_login(harness)

    assert harness.limiter.attempts == []
    assert harness.audit.events == []
