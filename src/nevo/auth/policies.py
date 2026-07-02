from datetime import timedelta

ROLE_IDLE_TIMEOUTS = {
    "student": timedelta(minutes=60),
    "teacher": timedelta(minutes=120),
    "senco_admin": timedelta(minutes=30),
    "other_admin": timedelta(minutes=120),
}


def idle_timeout_for_role(role: str) -> timedelta:
    try:
        return ROLE_IDLE_TIMEOUTS[role]
    except KeyError as error:
        raise ValueError(f"unsupported session role: {role}") from error


def requires_single_session(role: str) -> bool:
    return role == "student"
