from collections.abc import Callable
from datetime import UTC, datetime
from typing import Never
from uuid import uuid4

from nevo.auth.entities import (
    AuthPrincipal,
    AuthUser,
    IssuedSession,
    SessionDraft,
)
from nevo.auth.errors import (
    InvalidCredentialsError,
    InvalidSessionError,
    SessionExpiredError,
    SessionReplacedError,
)
from nevo.auth.policies import idle_timeout_for_role, requires_single_session
from nevo.auth.ports import (
    AuthAuditLog,
    CredentialHasher,
    LoginRateLimiter,
    SessionRepository,
    TokenService,
    UserRepository,
)

ACTIVE_STATUS = "active"
MANUAL_AUTH_METHODS = {"email_password", "pin"}


class AuthService:
    def __init__(
        self,
        *,
        users: UserRepository,
        sessions: SessionRepository,
        rate_limiter: LoginRateLimiter,
        audit_log: AuthAuditLog,
        credential_hasher: CredentialHasher,
        token_service: TokenService,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._users = users
        self._sessions = sessions
        self._rate_limiter = rate_limiter
        self._audit_log = audit_log
        self._credential_hasher = credential_hasher
        self._token_service = token_service
        self._now = now or (lambda: datetime.now(UTC))

    async def login_with_password(
        self,
        *,
        email: str,
        password: str,
        ip_address: str,
    ) -> IssuedSession:
        normalized_email = email.casefold().strip()
        identity_digest = self._token_service.protect_identifier(
            f"email:{normalized_email}"
        )
        ip_digest = self._token_service.protect_identifier(f"ip:{ip_address}")
        await self._rate_limiter.check(identity_digest, ip_digest)

        user = await self._users.find_by_email(normalized_email)
        verified = self._credential_hasher.verify_password(
            user.password_hash if user else None,
            password,
        )
        if (
            not user
            or not verified
            or not self._can_use_manual_method(user, "email_password")
        ):
            await self._reject_login(
                user=user,
                identity_digest=identity_digest,
                ip_digest=ip_digest,
            )

        return await self._complete_login(
            user=user,
            identity_digest=identity_digest,
            ip_digest=ip_digest,
        )

    async def login_with_pin(
        self,
        *,
        school_code: str,
        login_identifier: str,
        pin: str,
        ip_address: str,
    ) -> IssuedSession:
        normalized_school_code = school_code.casefold().strip()
        normalized_identifier = login_identifier.casefold().strip()
        identity_digest = self._token_service.protect_identifier(
            f"pin:{normalized_school_code}:{normalized_identifier}"
        )
        ip_digest = self._token_service.protect_identifier(f"ip:{ip_address}")
        await self._rate_limiter.check(identity_digest, ip_digest)

        user = await self._users.find_pin_user(
            normalized_school_code,
            normalized_identifier,
        )
        verified = self._credential_hasher.verify_pin(
            user.pin_hash if user else None,
            pin,
        )
        if (
            not user
            or user.role != "student"
            or not verified
            or not self._can_use_manual_method(user, "pin")
        ):
            await self._reject_login(
                user=user,
                identity_digest=identity_digest,
                ip_digest=ip_digest,
            )

        return await self._complete_login(
            user=user,
            identity_digest=identity_digest,
            ip_digest=ip_digest,
        )

    async def authenticate(self, access_token: str) -> AuthPrincipal:
        now = self._now()
        token_digest = self._token_service.digest(access_token)
        session = await self._sessions.find_by_digest(token_digest)
        if session is None:
            raise InvalidSessionError

        if session.revoked_at is not None:
            if session.revocation_reason == "concurrent_login":
                raise SessionReplacedError
            raise InvalidSessionError

        if session.expires_at <= now:
            await self._sessions.revoke(
                session.id,
                reason="expired",
                revoked_at=now,
            )
            await self._audit_log.record(
                "session_expired",
                occurred_at=now,
                user_id=session.user_id,
                session_id=session.id,
                identity_digest=None,
                ip_digest=None,
            )
            raise SessionExpiredError

        user = await self._users.find_by_id(session.user_id)
        if user is None or not self._is_active(user):
            await self._sessions.revoke(
                session.id,
                reason="user_unavailable",
                revoked_at=now,
            )
            raise InvalidSessionError

        expires_at = now + idle_timeout_for_role(session.role)
        await self._sessions.touch(
            session.id,
            last_seen_at=now,
            expires_at=expires_at,
        )
        return AuthPrincipal(
            user_id=session.user_id,
            role=session.role,
            session_id=session.id,
        )

    async def logout(self, access_token: str) -> None:
        now = self._now()
        session = await self._sessions.find_by_digest(
            self._token_service.digest(access_token)
        )
        if session is None or session.revoked_at is not None:
            return

        await self._sessions.revoke(
            session.id,
            reason="logout",
            revoked_at=now,
        )
        await self._audit_log.record(
            "logout",
            occurred_at=now,
            user_id=session.user_id,
            session_id=session.id,
            identity_digest=None,
            ip_digest=None,
        )

    async def _complete_login(
        self,
        *,
        user: AuthUser,
        identity_digest: str,
        ip_digest: str,
    ) -> IssuedSession:
        now = self._now()
        token, token_digest = self._token_service.issue()
        timeout = idle_timeout_for_role(user.role)
        draft = SessionDraft(
            id=uuid4(),
            user_id=user.id,
            role=user.role,
            token_digest=token_digest,
            created_at=now,
            last_seen_at=now,
            expires_at=now + timeout,
        )
        replaced = await self._sessions.create(
            draft,
            replace_active=requires_single_session(user.role),
        )
        await self._rate_limiter.record(
            identity_digest,
            ip_digest,
            succeeded=True,
            occurred_at=now,
        )
        await self._audit_log.record(
            "login_succeeded",
            occurred_at=now,
            user_id=user.id,
            session_id=draft.id,
            identity_digest=identity_digest,
            ip_digest=ip_digest,
            details={"method": user.auth_method},
        )
        if replaced is not None:
            await self._audit_log.record(
                "session_replaced",
                occurred_at=now,
                user_id=user.id,
                session_id=replaced.id,
                identity_digest=identity_digest,
                ip_digest=ip_digest,
                details={"replacement_session_id": str(draft.id)},
            )

        return IssuedSession(
            access_token=token,
            token_type="bearer",
            expires_at=draft.expires_at,
            user_id=user.id,
            role=user.role,
            replaced_session=replaced is not None,
        )

    async def _reject_login(
        self,
        *,
        user: AuthUser | None,
        identity_digest: str,
        ip_digest: str,
    ) -> Never:
        now = self._now()
        await self._rate_limiter.record(
            identity_digest,
            ip_digest,
            succeeded=False,
            occurred_at=now,
        )
        event_type = (
            "deactivated_login_attempt"
            if user is not None and not self._is_active(user)
            else "login_failed"
        )
        await self._audit_log.record(
            event_type,
            occurred_at=now,
            user_id=user.id if user else None,
            session_id=None,
            identity_digest=identity_digest,
            ip_digest=ip_digest,
        )
        raise InvalidCredentialsError

    @staticmethod
    def _is_active(user: AuthUser) -> bool:
        return user.status == ACTIVE_STATUS and user.deactivated_at is None

    @classmethod
    def _can_use_manual_method(cls, user: AuthUser, requested_method: str) -> bool:
        if not cls._is_active(user) or user.auth_method != requested_method:
            return False
        if user.school_auth_method is None:
            return True
        return user.school_auth_method in MANUAL_AUTH_METHODS
