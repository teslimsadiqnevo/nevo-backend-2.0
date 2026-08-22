from nevo.db import models  # noqa: F401
from nevo.db.base import Base


def test_accommodation_state_is_not_persisted_as_student_label() -> None:
    table_names = {table.name for table in Base.metadata.sorted_tables}
    all_column_names = {
        column.name
        for table in Base.metadata.sorted_tables
        for column in table.columns
    }

    assert "student_accommodations" not in table_names
    assert "learner_accommodations" not in table_names
    assert "active_accommodations" not in all_column_names
    assert "reading_accommodation_active" not in all_column_names
    assert "attention_accommodation_active" not in all_column_names
    assert "numerical_accommodation_active" not in all_column_names
