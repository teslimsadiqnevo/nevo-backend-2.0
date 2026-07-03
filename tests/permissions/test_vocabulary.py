import pytest

from nevo.domain.permissions.vocabulary import (
    PermissionScope,
    effective_scopes,
    navigation_for,
)


def test_permission_scope_contract_is_exact() -> None:
    assert [scope.value for scope in PermissionScope] == [
        "billing",
        "roster",
        "curriculum",
        "senco",
        "it_sso",
        "oversight",
        "teacher",
    ]


def test_teacher_and_senco_roles_keep_natural_scope() -> None:
    assert effective_scopes("teacher", frozenset()) == {
        PermissionScope.TEACHER
    }
    assert effective_scopes("senco_admin", frozenset()) == {
        PermissionScope.SENCO
    }


def test_navigation_is_stable_and_deduplicated() -> None:
    navigation = navigation_for(
        frozenset(
            {
                PermissionScope.SENCO,
                PermissionScope.TEACHER,
            }
        )
    )

    assert navigation == (
        "dashboard",
        "lessons",
        "students",
        "insights",
        "iep_exporter",
        "connect",
    )


def test_unknown_role_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unsupported role"):
        effective_scopes("unknown", frozenset())
