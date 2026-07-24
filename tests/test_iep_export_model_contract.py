from nevo.db.models.export import IepExport, IepExportShare, StudentRecordEvent


def test_iep_export_tables_are_mapped() -> None:
    assert IepExport.__tablename__ == "iep_exports"
    assert IepExportShare.__tablename__ == "iep_export_shares"
    assert StudentRecordEvent.__tablename__ == "student_record_events"

    export_columns = {column.name for column in IepExport.__table__.columns}
    assert {
        "student_id",
        "requested_by_user_id",
        "period_start",
        "period_end",
        "status",
        "export_content",
        "source_summary",
        "annotations",
        "reviewed_by_user_id",
        "reviewed_at",
    }.issubset(export_columns)

    share_columns = {column.name for column in IepExportShare.__table__.columns}
    assert {"export_id", "student_id", "parent_id", "shared_by_user_id"}.issubset(
        share_columns
    )
