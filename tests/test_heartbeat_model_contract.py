from sqlalchemy import UniqueConstraint

from nevo.db import models  # noqa: F401
from nevo.db.base import Base


def unique_constraint_names() -> set[str]:
    return {
        constraint.name
        for constraint in Base.metadata.tables[
            "system_heartbeats"
        ].constraints
        if isinstance(constraint, UniqueConstraint) and constraint.name
    }


def test_system_heartbeat_table_exists() -> None:
    assert "system_heartbeats" in Base.metadata.tables


def test_system_heartbeat_beat_date_is_unique_and_required() -> None:
    columns = Base.metadata.tables["system_heartbeats"].columns
    assert columns["beat_date"].nullable is False
    assert "uq_system_heartbeats_beat_date" in unique_constraint_names()
