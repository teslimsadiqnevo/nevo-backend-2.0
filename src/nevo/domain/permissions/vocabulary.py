from enum import StrEnum


class PermissionScope(StrEnum):
    BILLING = "billing"
    ROSTER = "roster"
    CURRICULUM = "curriculum"
    SENCO = "senco"
    IT_SSO = "it_sso"
    OVERSIGHT = "oversight"
    TEACHER = "teacher"


IMPLICIT_SCOPES_BY_ROLE: dict[str, frozenset[PermissionScope]] = {
    "student": frozenset(),
    "teacher": frozenset({PermissionScope.TEACHER}),
    "senco_admin": frozenset({PermissionScope.SENCO}),
    "other_admin": frozenset(),
}

NAVIGATION_BY_SCOPE: dict[PermissionScope, tuple[str, ...]] = {
    PermissionScope.BILLING: ("billing",),
    PermissionScope.ROSTER: ("classes", "students", "team"),
    PermissionScope.CURRICULUM: ("curriculum", "lessons"),
    PermissionScope.SENCO: ("students", "insights", "iep_exporter"),
    PermissionScope.IT_SSO: ("integrations", "settings"),
    PermissionScope.OVERSIGHT: ("overview", "reports", "team"),
    PermissionScope.TEACHER: (
        "dashboard",
        "lessons",
        "students",
        "insights",
        "connect",
    ),
}

NAVIGATION_ORDER = (
    "overview",
    "dashboard",
    "classes",
    "lessons",
    "curriculum",
    "students",
    "insights",
    "iep_exporter",
    "reports",
    "billing",
    "integrations",
    "settings",
    "team",
    "connect",
)


def effective_scopes(
    role: str,
    assigned_scopes: frozenset[PermissionScope],
) -> frozenset[PermissionScope]:
    try:
        implicit = IMPLICIT_SCOPES_BY_ROLE[role]
    except KeyError as error:
        raise ValueError(f"Unsupported role: {role}") from error
    return assigned_scopes | implicit


def navigation_for(scopes: frozenset[PermissionScope]) -> tuple[str, ...]:
    allowed = {
        destination
        for scope in scopes
        for destination in NAVIGATION_BY_SCOPE[scope]
    }
    return tuple(item for item in NAVIGATION_ORDER if item in allowed)
