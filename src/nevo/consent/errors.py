class ConsentError(Exception):
    code = "consent_error"
    public_message = "The consent request could not be completed."


class MissingSchoolContextError(ConsentError):
    code = "missing_school_context"
    public_message = "A school context is required."


class StudentNotFoundError(ConsentError):
    code = "student_not_found"
    public_message = "The student was not found in this school."


class InvalidParentContactError(ConsentError):
    code = "invalid_parent_contact"
    public_message = "Enter a valid parent email address or phone number."


class InvalidConsentMethodError(ConsentError):
    code = "invalid_consent_method"
    public_message = "That confirmation method is not valid for this path."


class InvalidConsentInvitationError(ConsentError):
    code = "invalid_consent_invitation"
    public_message = "This consent link is invalid, expired, or already used."


class ParentAccountConflictError(ConsentError):
    code = "parent_account_conflict"
    public_message = "That contact belongs to an incompatible account."


class StudentConsentAccessError(ConsentError):
    code = "student_consent_access_denied"
    public_message = "Only a student can check this consent gate."


class ConsentRequiredError(ConsentError):
    code = "consent_required"
    public_message = "Parent or school consent is required to continue."


class ConsentWithdrawnError(ConsentError):
    code = "consent_withdrawn"
    public_message = "A parent or guardian has withdrawn consent for this learner."


class ParentAlreadyRefusedError(ConsentError):
    """This parent was asked about this child and did not consent.

    The agreement's wording is that we keep a minimal record of the refusal
    so we do not contact them again. Enforced where the contact would happen,
    because a rule against contacting somebody is worth nothing if it lives
    only in a screen.
    """

    code = "parent_already_refused"
    public_message = (
        "This parent was already asked about this learner and did not consent. "
        "Nevo does not contact them again. Speak to them directly if something "
        "has changed."
    )
