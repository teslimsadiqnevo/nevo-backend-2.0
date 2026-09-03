from sqlalchemy import Enum, Index

from nevo.db import models  # noqa: F401
from nevo.db.base import Base


def enum_values(column_name: str) -> list[str]:
    column = Base.metadata.tables["partner_inquiries"].columns[column_name]
    assert isinstance(column.type, Enum)
    return list(column.type.enums)


def index_names() -> set[str]:
    return {
        index.name
        for index in Base.metadata.tables["partner_inquiries"].indexes
        if isinstance(index, Index) and index.name
    }


def test_partner_inquiry_table_and_enums_exist() -> None:
    assert "partner_inquiries" in Base.metadata.tables
    assert enum_values("role") == [
        "school_owner",
        "proprietor",
        "senco",
        "head_of_learning",
        "head_teacher",
        # The TOSSE dropdown offers both; without them a teacher or a parent
        # at the stand would be recorded as "other".
        "teacher",
        "parent",
        "other",
    ]
    assert enum_values("contact_method") == ["email", "phone"]


def test_partner_inquiry_optional_message_and_required_fields() -> None:
    columns = Base.metadata.tables["partner_inquiries"].columns
    assert columns["message"].nullable is True
    assert columns["full_name"].nullable is False
    assert columns["school_name"].nullable is False
    assert columns["contact"].nullable is False


def test_partner_inquiry_created_at_is_indexed() -> None:
    assert "ix_partner_inquiries_created_at" in index_names()
