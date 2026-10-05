from datetime import timedelta

ROLE_IDLE_TIMEOUTS = {
    "student": timedelta(minutes=60),
    "teacher": timedelta(minutes=120),
    "senco_admin": timedelta(minutes=30),
    "other_admin": timedelta(minutes=120),
    "parent_guardian": timedelta(minutes=120),
}


#: The longest a single sign-in may last, however active it stays.
#:
#: The idle timeout above slides on every authenticated request, which is
#: what keeps a child from being thrown out mid-lesson - but it means a tab
#: left open and polling renews forever, so an idle timeout alone is not a
#: session limit. This is the ceiling: once a session is this old it ends
#: whatever it is doing, and the person signs in again. Ask B57.
#:
#: A school day for a child, so one sign-in cannot carry into the next day on
#: a shared tablet. Longer for staff, who work across a day and whose
#: sign-in is their own.
ROLE_ABSOLUTE_LIFETIMES = {
    "student": timedelta(hours=10),
    "teacher": timedelta(hours=14),
    "senco_admin": timedelta(hours=12),
    "other_admin": timedelta(hours=14),
    "parent_guardian": timedelta(hours=14),
}

#: Used for a role nothing above names, so an unknown role is capped rather
#: than uncapped.
DEFAULT_ABSOLUTE_LIFETIME = timedelta(hours=12)


def absolute_lifetime_for_role(role: str) -> timedelta:
    """The longest this role's session may live, counted from sign-in."""

    return ROLE_ABSOLUTE_LIFETIMES.get(role, DEFAULT_ABSOLUTE_LIFETIME)


def idle_timeout_for_role(role: str) -> timedelta:
    try:
        return ROLE_IDLE_TIMEOUTS[role]
    except KeyError as error:
        raise ValueError(f"unsupported session role: {role}") from error


def requires_single_session(role: str) -> bool:
    return role == "student"
