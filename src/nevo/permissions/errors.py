class PermissionError(Exception):
    code = "permission_error"
    public_message = "The requested permission operation could not be completed."


class PermissionDeniedError(PermissionError):
    code = "permission_denied"
    public_message = "You do not have permission to perform this action."


class TeamMemberNotFoundError(PermissionError):
    code = "team_member_not_found"
    public_message = "The requested team member was not found."


class TeamMemberAlreadyExistsError(PermissionError):
    code = "team_member_exists"
    public_message = "A user with this email already belongs to the platform."


class InvalidInvitationError(PermissionError):
    code = "invalid_invitation"
    public_message = "This invitation is invalid or has expired."


class LastOversightAdminError(PermissionError):
    code = "last_oversight_admin"
    public_message = "A school must retain at least one oversight administrator."


class SelfScopeRemovalError(PermissionError):
    code = "cannot_remove_own_oversight"
    public_message = "You cannot remove your own oversight permission."


class SsoManagedTeamError(PermissionError):
    code = "sso_managed_team"
    public_message = "This school's team is managed through its SSO provider."


class InvalidAdminRoleError(PermissionError):
    code = "invalid_admin_role"
    public_message = "Student accounts cannot be added to the admin team."
