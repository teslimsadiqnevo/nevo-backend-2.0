"""A teacher's request for help with a learner account is not platform noise.

Two separate problems, both reported from the console on 6 November.

It was filed under ACCOUNT, the switch the settings screen calls Platform, so
an administrator who muted platform notices stopped hearing teachers asking
for help with a locked-out child. It is a colleague asking a person to do
something, which is what MESSAGES is for.

And it went to every administrator in the school, so a request about one
child arrived for the finance lead and the IT contact alike.
"""

from __future__ import annotations

import inspect

from nevo.api import frontend_unblockers
from nevo.domain.accounts.vocabulary import (
    NOTIFICATION_CATEGORY_BY_TYPE,
    NotificationCategory,
    NotificationType,
    notification_category,
)
from nevo.domain.permissions.vocabulary import PermissionScope


def test_a_help_request_is_not_muted_by_the_platform_switch() -> None:
    assert (
        notification_category(NotificationType.DEACTIVATED_STUDENT_SUPPORT_REQUESTED)
        is NotificationCategory.MESSAGES
    )


def test_the_category_mapping_has_one_source_of_truth() -> None:
    # The mapping was declared and then re-applied with .update() further
    # down the same module, and the copy won. Editing the declaration changed
    # nothing the product did, so a category fix could look applied and have
    # no effect. Pinned because that failure is invisible.
    import nevo.domain.accounts.vocabulary as vocabulary

    source = inspect.getsource(vocabulary)
    assert "NOTIFICATION_CATEGORY_BY_TYPE.update(" not in source


def test_every_kind_still_has_a_category() -> None:
    # Removing the duplicate must not drop anything: the declaration has to
    # be a superset of what the copy set, or a type silently becomes
    # unmutable.
    assert set(NOTIFICATION_CATEGORY_BY_TYPE) == set(NotificationType)


def test_the_request_goes_to_the_admins_who_handle_the_roster() -> None:
    helper = inspect.getsource(frontend_unblockers._admins_who_handle_the_roster)
    assert "PermissionScope.ROSTER" in helper
    assert "AdminScopeAssignment.revoked_at.is_(None)" in helper
    # Implicit as well as assigned, so a role that carries the scope by
    # definition is not left out.
    assert "IMPLICIT_SCOPES_BY_ROLE" in helper
    assert "_admins_who_handle_the_roster" in inspect.getsource(
        frontend_unblockers.request_admin_support_for_student
    )


def test_a_school_that_has_not_split_its_scopes_still_gets_told() -> None:
    # Silence is worse than one notice reaching the wrong desk: a teacher is
    # waiting on a child's account, and a school that has not divided its
    # scopes up is the common case rather than a misconfiguration.
    helper = inspect.getsource(frontend_unblockers._admins_who_handle_the_roster)
    assert "if holders:" in helper
    assert "return admins" in helper


def test_roster_scope_is_the_one_that_governs_students() -> None:
    from nevo.domain.permissions.vocabulary import NAVIGATION_BY_SCOPE

    assert "students" in NAVIGATION_BY_SCOPE[PermissionScope.ROSTER]
