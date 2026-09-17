"""Every kind of notification is actually produced by something.

NotificationType declared nine kinds and two were ever written: an admin
welcome and a PIN reset request. The other seven had categories, preference
switches and a delivery worker waiting for them, and nothing raised any of
them - so a teacher could mute a notification that did not exist and wait for
one that was never coming.
"""

from __future__ import annotations

import subprocess

import pytest

from nevo.domain.accounts.vocabulary import NotificationType

#: Raised by code, with where to look. A kind that cannot be pointed at a
#: trigger is a kind nobody receives.
TRIGGERED: dict[NotificationType, str] = {
    NotificationType.ADMIN_WELCOME: "a school finishes registration",
    NotificationType.PIN_RESET_REQUESTED: "a student asks for a PIN reset",
    NotificationType.INVOICE_ISSUED: "an invoice is issued",
    NotificationType.SSO_NEEDS_ATTENTION: "a roster sync is refused by the provider",
    NotificationType.ROSTER_SYNC_COMPLETED: "a roster sync finishes cleanly",
    NotificationType.ROSTER_SYNC_NEEDS_ATTENTION: "a sync leaves classes unmapped",
    NotificationType.CONSENT_ACTION_REQUIRED: "a consent request goes out to a parent",
    NotificationType.ATTENTION_SUMMARY: "the weekly digest job runs",
    NotificationType.MODALITY_SHIFT: "a lesson finishes in which delivery changed",
}

#: Nothing left. Every kind is raised by something, which is the state this
#: file exists to keep: a kind nobody raises is a preference switch that
#: silences nothing and a teacher waiting for a message never coming.
AWAITING_A_TRIGGER: set[NotificationType] = set()


def test_every_kind_is_accounted_for() -> None:
    # A new kind must land in one list or the other, rather than quietly
    # joining the seven that nothing produced.
    assert set(TRIGGERED) | AWAITING_A_TRIGGER == set(NotificationType)
    assert not set(TRIGGERED) & AWAITING_A_TRIGGER


@pytest.mark.parametrize("notification_type", sorted(TRIGGERED, key=lambda t: t.value))
def test_a_triggered_kind_appears_in_the_source(notification_type: NotificationType) -> None:
    found = subprocess.run(
        ["grep", "-rl", notification_type.value, "src/nevo/"],
        capture_output=True,
        text=True,
    ).stdout
    callers = [
        line
        for line in found.splitlines()
        if "vocabulary.py" not in line and "dispatch.py" not in line
    ]

    assert callers, f"{notification_type.value} is claimed as triggered and is not raised"
