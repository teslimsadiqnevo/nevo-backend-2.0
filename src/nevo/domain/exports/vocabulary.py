from enum import StrEnum


class IepExportStatus(StrEnum):
    DRAFT = "draft"
    FINAL = "final"


class IepExportShareStatus(StrEnum):
    SHARED = "shared"
    REVOKED = "revoked"


class StudentRecordEventType(StrEnum):
    EXPORT_DRAFT_CREATED = "export_draft_created"
    EXPORT_DRAFT_EDITED = "export_draft_edited"
    EXPORT_FINALIZED = "export_finalized"
    EXPORT_SHARED = "export_shared"
