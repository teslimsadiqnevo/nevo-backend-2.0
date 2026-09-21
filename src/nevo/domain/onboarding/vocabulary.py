from enum import StrEnum


class OnboardingStage(StrEnum):
    """Where a school is between uploading a file and opening its workspace.

    The order is the ruling: upload, derive, confirm, pay, activate. A stage
    is typed so the server decides which step a school is on, rather than a
    console inferring it from which arrays happen to be empty.
    """

    #: Files can be uploaded and re-uploaded. Nothing exists yet.
    UPLOADING = "uploading"
    #: The school has confirmed the derived list. Classes and people exist,
    #: inactive, and the invoice can be raised.
    CONFIRMED = "confirmed"
    #: Priced and waiting on money. A Nigerian school paying by transfer sits
    #: here, sometimes for days, which is why it is a state and not a spinner.
    AWAITING_PAYMENT = "awaiting_payment"
    #: Paid. Accounts, invitations, consent requests and credentials are out.
    ACTIVATED = "activated"


class OnboardingRowKind(StrEnum):
    TEACHER = "teacher"
    STUDENT = "student"
