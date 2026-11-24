import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Never
from uuid import UUID, uuid4

from nevo.auth.entities import (
    AuthPrincipal,
    AuthUser,
    IssuedSession,
    SessionDraft,
)
from nevo.auth.errors import (
    AccountPausedError,
    AuthError,
    InvalidCredentialsError,
    InvalidSessionError,
    SchoolCodeRequiredError,
    SessionExpiredError,
    SessionReplacedError,
    SessionRevokedError,
)
from nevo.auth.policies import (
    absolute_lifetime_for_role,
    idle_timeout_for_role,
    requires_single_session,
)
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

    @staticmethod
    async def _together(*awaitables):
        """Run independent database work at the same time, not one after the
        other, and still fail on the first thing that failed.

        Measured on the dyno, 20 November: a sign-in made four queries - not
        the thirty that five seconds suggested - and each one cost about
        280ms, because the dyno is in the US and the database is in
        Frankfurt. Three of those four were sequential for no reason: the
        rate-limit check does not depend on the user lookup, and recording an
        attempt does not depend on writing an audit event.

        return_exceptions so neither is left running after the other raises,
        which would leak a session and log an unretrieved task error. The
        first failure is re-raised in argument order, so the rate limiter
        still wins over anything the lookup says.
        """
        results = await asyncio.gather(*awaitables, return_exceptions=True)
        for result in results:
            if isinstance(result, BaseException):
                raise result
        return results

    async def login_with_password(
        self,
        *,
        email: str,
        password: str,
        ip_address: str,
    ) -> IssuedSession:
        normalized_email = email.casefold().strip()
        identity_digest = self._token_service.protect_identifier(f"email:{normalized_email}")
        ip_digest = self._token_service.protect_identifier(f"ip:{ip_address}")
        # Two independent reads, one wall-clock round trip instead of two.
        # A rate-limited caller now also costs a user lookup, which is a read
        # on the rare path and buys 280ms on the common one.
        _, user = await self._together(
            self._rate_limiter.check(identity_digest, ip_digest),
            self._users.find_by_email(normalized_email),
        )
        verified = await self._credential_hasher.verify_password_async(
            user.password_hash if user else None,
            password,
        )
        if user is not None and verified and self._is_paused(user):
            await self._reject_login(
                user=user,
                identity_digest=identity_digest,
                ip_digest=ip_digest,
                error=AccountPausedError,
            )
        if not user or not verified or not self._can_use_manual_method(user, "email_password"):
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

    async def login_with_parent_contact(
        self,
        *,
        contact: str,
        password: str,
        ip_address: str,
        school_code: str | None = None,
    ) -> IssuedSession:
        """Sign a parent in by whichever contact their school holds.

        A parent reached by SMS has no email address on their account, so the
        email-only path left them with credentials they could not use. The
        school chose the channel, not the parent, and the sign-in screen
        should not make them guess which one it was.
        """
        normalized = contact.casefold().strip()
        identity_digest = self._token_service.protect_identifier(f"parent:{normalized}")
        ip_digest = self._token_service.protect_identifier(f"ip:{ip_address}")
        await self._rate_limiter.check(identity_digest, ip_digest)

        candidates = await self._users.find_parents_by_contact(
            normalized,
            school_code=school_code.casefold().strip() if school_code else None,
        )
        if len(candidates) > 1:
            # The same phone can belong to a parent at two schools. Choosing
            # one would sign them into the wrong child's records.
            raise SchoolCodeRequiredError
        user = candidates[0] if candidates else None
        verified = await self._credential_hasher.verify_password_async(
            user.password_hash if user else None,
            password,
        )
        if not user or not verified or not self._is_active(user):
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
        verified = await self._credential_hasher.verify_pin_async(
            user.pin_hash if user else None,
            pin,
        )
        if user is not None and verified and user.role == "student" and self._is_paused(user):
            # The PIN was right. Telling them the account is paused reveals
            # nothing they could not already infer from holding the credential,
            # and it is the difference between a screen that explains and one
            # that tells a child they cannot type their own PIN.
            await self._reject_login(
                user=user,
                identity_digest=identity_digest,
                ip_digest=ip_digest,
                error=AccountPausedError,
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
            # Three different endings, three different screens. They used to
            # collapse into one invalid_session, so a client could not tell a
            # deliberate sign-out from an ordinary timeout.
            if session.revocation_reason == "concurrent_login":
                raise SessionReplacedError
            if session.revocation_reason == "user_unavailable":
                raise AccountPausedError
            raise SessionRevokedError

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

        # The idle timeout slides on every request, so without this a tab
        # left open and polling renews indefinitely. Counted from sign-in,
        # not from the last request. Ask B57.
        if now - session.created_at >= absolute_lifetime_for_role(session.role):
            await self._sessions.revoke(
                session.id,
                reason="absolute_lifetime_reached",
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
            # A learner whose parent withdrew consent lands here. Saying so
            # is what lets the app show the paused screen rather than a bare
            # "signed out" that reads like a fault.
            raise AccountPausedError

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
            account_type=user.account_type,
            school_id=user.school_id,
        )

    async def issue_for_provisioned_user(self, user_id: UUID) -> IssuedSession:
        """Issue the first session after a trusted provisioning flow completes."""
        user = await self._users.find_by_id(user_id)
        if user is None:
            raise InvalidCredentialsError
        if not self._is_active(user):
            raise AccountPausedError
        identity_digest = self._token_service.protect_identifier(f"provisioned:{user.id}")
        return await self._complete_login(
            user=user,
            identity_digest=identity_digest,
            ip_digest=self._token_service.protect_identifier("ip:provisioning"),
        )

    async def logout(self, access_token: str) -> None:
        now = self._now()
        session = await self._sessions.find_by_digest(self._token_service.digest(access_token))
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

    async def refresh(self, access_token: str) -> IssuedSession:
        """Extend an active session and return the expiry the client should keep.

        Authentication already uses a sliding idle timeout. This method makes
        that renewed deadline visible to clients without rotating the token or
        interrupting a student's in-progress lesson.
        """
        principal = await self.authenticate(access_token)
        session = await self._sessions.find_by_digest(self._token_service.digest(access_token))
        if session is None or session.revoked_at is not None:
            raise InvalidSessionError
        user = await self._users.find_by_id(principal.user_id)
        return IssuedSession(
            access_token=access_token,
            token_type="bearer",
            expires_at=session.expires_at,
            user_id=principal.user_id,
            role=principal.role,
            replaced_session=False,
            preferences=dict(user.preferences) if user else {},
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
        # After the session exists, deliberately. Recording a successful
        # login for a session that failed to be created would leave an audit
        # trail that disagrees with what actually happened, which is worse
        # than one more round trip. These two, though, are independent of
        # each other and of the create's result, so they go together.
        await self._together(
            self._rate_limiter.record(
                identity_digest,
                ip_digest,
                succeeded=True,
                occurred_at=now,
            ),
            self._audit_log.record(
                "login_succeeded",
                occurred_at=now,
                user_id=user.id,
                session_id=draft.id,
                identity_digest=identity_digest,
                ip_digest=ip_digest,
                details={"method": user.auth_method},
            ),
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
            preferences=dict(user.preferences),
        )

    async def _reject_login(
        self,
        *,
        user: AuthUser | None,
        identity_digest: str,
        ip_digest: str,
        error: type[AuthError] = InvalidCredentialsError,
    ) -> Never:
        now = self._now()
        event_type = (
            "deactivated_login_attempt"
            if user is not None and not self._is_active(user)
            else "login_failed"
        )
        # Both still committed before the caller is told anything - the
        # attempt is what makes rate limiting work and the audit event is a
        # security record, so neither may be dropped or deferred. They are
        # simply written at the same time rather than one after the other.
        await self._together(
            self._rate_limiter.record(
                identity_digest,
                ip_digest,
                succeeded=False,
                occurred_at=now,
            ),
            self._audit_log.record(
                event_type,
                occurred_at=now,
                user_id=user.id if user else None,
                session_id=None,
                identity_digest=identity_digest,
                ip_digest=ip_digest,
            ),
        )
        raise error

    @staticmethod
    def _is_paused(user: AuthUser) -> bool:
        """Switched off, as opposed to never switched on.

        Only this is worth saying out loud. Someone holding the credential for
        a paused account already knows it exists, and telling them beats
        telling a child their own PIN is wrong. An invited account is a
        different thing - it is not theirs to use yet - so that stays a
        generic refusal, which is what the enumeration tests protect.
        """
        return user.status == "deactivated" or user.deactivated_at is not None

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
