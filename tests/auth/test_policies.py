from datetime import timedelta

import pytest

from nevo.auth.policies import idle_timeout_for_role, requires_single_session


@pytest.mark.parametrize(
    ("role", "minutes"),
    [
        ("student", 60),
        ("teacher", 120),
        ("senco_admin", 30),
        ("other_admin", 120),
    ],
)
def test_role_idle_timeouts(role: str, minutes: int) -> None:
    assert idle_timeout_for_role(role) == timedelta(minutes=minutes)


def test_only_students_require_a_single_session() -> None:
    assert requires_single_session("student")
    assert not requires_single_session("teacher")
    assert not requires_single_session("senco_admin")
    assert not requires_single_session("other_admin")


def test_unknown_role_is_rejected() -> None:
    with pytest.raises(ValueError, match="unsupported session role"):
        idle_timeout_for_role("unknown")
