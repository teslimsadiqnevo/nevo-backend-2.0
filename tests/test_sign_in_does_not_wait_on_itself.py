"""A sign-in must not pay for round trips it does not need.

Measured on the dyno against production, 20 November. A failed sign-in made
four queries - not the thirty that five seconds suggested - and each one cost
about 280ms, because the dyno is in the US and the database is in Frankfurt.
The email lookup is not slow: EXPLAIN ANALYZE shows an index scan on
uq_users_email_ci in 0.048ms over 122 rows. The time is distance, multiplied
by how many times we go there and back.

Three of the four were sequential for no reason. The rate-limit check does
not depend on the user lookup, and recording a failed attempt does not depend
on writing an audit event. They now go together.

What must not change, and is asserted below: both writes are still awaited
before the caller is told anything. The attempt record is what makes rate
limiting work, and the audit event is a security record. Deferring either to
a background task would make sign-in look faster by quietly weakening
brute-force protection.
"""

from __future__ import annotations

import inspect

from nevo.auth.service import AuthService


def test_the_two_reads_happen_together() -> None:
    source = inspect.getsource(AuthService.login_with_password)
    assert "self._together(" in source
    assert "self._rate_limiter.check(" in source
    assert "self._users.find_by_email(" in source
    # Neither may be awaited on its own any more, or the round trip is back.
    assert "await self._rate_limiter.check(" not in source
    assert "await self._users.find_by_email(" not in source


def test_the_rejection_writes_happen_together_and_are_still_awaited() -> None:
    source = inspect.getsource(AuthService._reject_login)
    assert "await self._together(" in source
    assert "self._rate_limiter.record(" in source
    assert "self._audit_log.record(" in source
    # The one thing that would be a security regression: not waiting.
    assert "create_task" not in source
    assert "ensure_future" not in source


def test_a_successful_sign_in_records_only_after_the_session_exists() -> None:
    """Order matters here in a way it does not elsewhere.

    Recording a successful login for a session that failed to be created
    would leave an audit trail disagreeing with what happened, which is worse
    than one more round trip.
    """
    source = inspect.getsource(AuthService._complete_login)
    create_at = source.index("self._sessions.create(")
    together_at = source.index("self._together(")
    assert create_at < together_at
    assert "await self._sessions.create(" in source


def test_nothing_is_fire_and_forget() -> None:
    """Across the whole service, not just the paths changed today."""
    source = inspect.getsource(AuthService)
    assert "create_task" not in source
    assert "ensure_future" not in source


def test_the_first_failure_wins_in_argument_order() -> None:
    """The rate limiter must still beat whatever the lookup says, or a
    rate-limited caller could be told their password was wrong instead."""
    source = inspect.getsource(AuthService._together)
    assert "return_exceptions=True" in source
    assert "raise result" in source
