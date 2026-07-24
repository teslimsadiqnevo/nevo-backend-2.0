class ExportWorkflowError(Exception):
    code = "export_workflow_error"
    public_message = "The export workflow could not be completed."


class ExportNotFoundError(ExportWorkflowError):
    code = "export_not_found"
    public_message = "Export was not found."


class ExportPermissionError(ExportWorkflowError):
    code = "export_permission_denied"
    public_message = "You do not have permission to complete this export action."


class ExportReviewRequiredError(ExportWorkflowError):
    code = "senco_review_required"
    public_message = "SENCo review is required before this export can be finalized."


class ExportAlreadyFinalError(ExportWorkflowError):
    code = "export_already_final"
    public_message = "Final exports cannot be edited."


class ExportShareRequiresFinalError(ExportWorkflowError):
    code = "export_share_requires_final"
    public_message = "Only final exports can be shared."


class ParentShareTargetError(ExportWorkflowError):
    code = "parent_share_target_invalid"
    public_message = "The parent or guardian account is not linked to this student."
