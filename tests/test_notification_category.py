"""Muting a category has to silence something.

The email worker decides what to suppress by joining a user's preferences on
notifications.category, and sends when no preference matches. One kind was
stored as the column default "general", which is not one of the seven
categories a preference can be set for - so it matched nothing, and a teacher
who muted attention kept receiving attention emails.
"""

from __future__ import annotations

import inspect
import uuid

import pytest

from nevo.db.models.frontend_support import Notification, _category_follows_type
from nevo.domain.accounts.vocabulary import NotificationType, notification_category
from nevo.notifications.worker import NotificationEmailWorker


def _notification(notification_type: str) -> Notification:
    return Notification(
        recipient_id=uuid.uuid4(),
        recipient_role="teacher",
        type=notification_type,
        title="A title",
        description="A description",
    )


@pytest.mark.parametrize("notification_type", list(NotificationType))
def test_the_stored_category_follows_the_type(notification_type: NotificationType) -> None:
    record = _notification(notification_type.value)

    _category_follows_type(None, None, record)

    assert record.category == notification_category(notification_type).value


def test_the_kind_that_was_wrong_in_production() -> None:
    # Stored as "general", which no preference row can match.
    record = _notification("attention_summary")

    _category_follows_type(None, None, record)

    assert record.category == "attention"


def test_a_type_nothing_maps_is_left_alone_rather_than_guessed() -> None:
    record = _notification("something_added_later")
    record.category = "account"

    _category_follows_type(None, None, record)

    # Not silently relabelled: a wrong category is a wrong mute.
    assert record.category == "account"


def test_the_worker_still_matches_on_the_column_it_joins() -> None:
    """The fix is the column being right, not the worker changing.

    If this join ever moves to another field, the listener above stops being
    what makes muting work and this test should fail rather than let it rot.
    """
    source = inspect.getsource(NotificationEmailWorker)

    assert "NotificationPreference.category == Notification.category" in source
