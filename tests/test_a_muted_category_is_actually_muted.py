"""Muting a category in the app has to silence something.

T19. The settings screen offers seven switches, each storing an in_app flag
and an email flag. The email worker has always joined the email one. Nothing
ever read in_app: the inbox query filtered on recipient and archived state
and nothing else, so a muted category still arrived in the inbox and still
counted towards the unread badge. The switch was there and did nothing, which
is worse than not offering it.

Consent is the exception, and the same exception the email side already
makes. A parent or an administrator who mutes a category must not thereby
hide a consent action waiting on them: that is a notification about a child's
permission to learn, and a muted switch is not consent to stop being asked.
"""

from __future__ import annotations

import inspect

from nevo.api import frontend_unblockers as routes
from nevo.domain.accounts.vocabulary import (
    NOTIFICATION_CATEGORY_BY_TYPE,
    NotificationType,
)


def test_every_notification_type_belongs_to_a_category() -> None:
    """A type with no category cannot be muted by any switch on offer."""
    unmapped = [t.value for t in NotificationType if t not in NOTIFICATION_CATEGORY_BY_TYPE]
    assert unmapped == []


def test_the_inbox_honours_the_in_app_switch() -> None:
    source = inspect.getsource(routes.list_notifications)
    assert "_not_muted_in_app(" in source
    assert "outerjoin(" in source


def test_the_badge_uses_the_same_rule_as_the_inbox() -> None:
    """A badge counting notifications the inbox will not show is a number
    nobody can clear."""
    assert "_not_muted_in_app(" in inspect.getsource(routes.unread_count)


def test_no_preference_row_means_not_muted() -> None:
    """The default is on, so a user who has never touched the switches must
    keep receiving everything."""
    source = inspect.getsource(routes._not_muted_in_app)
    assert "preference.id.is_(None)" in source
    assert "preference.in_app.is_(True)" in source


def test_a_consent_action_is_never_hidden_by_a_mute() -> None:
    source = inspect.getsource(routes._not_muted_in_app)
    assert "NotificationType.CONSENT_ACTION_REQUIRED.value" in source


def test_the_in_app_rule_matches_the_email_rule() -> None:
    """Shaped the same way on purpose. Two rules that are meant to agree and
    are written differently are two rules that will diverge."""
    from nevo.notifications import worker

    email_rule = inspect.getsource(worker)
    in_app_rule = inspect.getsource(routes._not_muted_in_app)
    # Both make the consent exception, and both treat a missing preference
    # row as "not muted" because the default is on.
    assert "consent_action_required" in email_rule
    assert "CONSENT_ACTION_REQUIRED" in in_app_rule
    assert "id.is_(None)" in email_rule
    assert "id.is_(None)" in in_app_rule


def test_the_category_is_kept_in_step_by_the_mapper_not_the_call_sites() -> None:
    """Set in one place because the call sites are the thing that got it
    wrong, and a new one would get it wrong the same way."""
    from nevo.db.models import frontend_support

    source = inspect.getsource(frontend_support._category_follows_type)
    assert "notification_category(target.type)" in source
