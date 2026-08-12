from sqlalchemy import CheckConstraint, Enum

from nevo.db import models  # noqa: F401
from nevo.db.base import Base


def check_names(table_name: str) -> set[str]:
    return {
        constraint.name or ""
        for constraint in Base.metadata.tables[table_name].constraints
        if isinstance(constraint, CheckConstraint)
    }


def test_sso_configuration_tracks_connection_health() -> None:
    columns = Base.metadata.tables["school_sso_configurations"].columns

    status = columns["connection_status"]
    assert isinstance(status.type, Enum)
    assert status.type.enums == ["connected", "needs_attention", "disconnected"]
    assert status.nullable is False

    for column in (
        "last_connection_error",
        "connection_checked_at",
        "reauthorised_at",
        "next_scheduled_sync_at",
        "disconnected_at",
        "disconnected_by_user_id",
    ):
        assert columns[column].nullable is True


def test_disconnect_state_is_consistent_in_the_database() -> None:
    assert any(
        name.endswith("disconnected_matches_timestamp")
        for name in check_names("school_sso_configurations")
    )


def test_disconnecting_never_cascades_into_accounts() -> None:
    """A soft disable must not be able to remove a user row."""
    table = Base.metadata.tables["school_sso_configurations"]
    for constraint in table.foreign_key_constraints:
        for element in constraint.elements:
            if element.column.table.name == "users":
                assert element.ondelete == "SET NULL"


def test_sync_runs_record_failure_and_attribution() -> None:
    columns = Base.metadata.tables["roster_sync_runs"].columns

    assert columns["failure_reason"].nullable is True
    assert columns["triggered_manually"].nullable is False
    assert columns["triggered_by_user_id"].nullable is True


def test_sync_issues_carry_a_resolution_hint() -> None:
    columns = Base.metadata.tables["roster_sync_issues"].columns
    assert "resolution_hint" in columns
    assert columns["resolution_hint"].nullable is True
