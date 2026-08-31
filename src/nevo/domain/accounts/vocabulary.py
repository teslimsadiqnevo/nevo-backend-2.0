from enum import StrEnum


class UserRole(StrEnum):
    """Primary account role.

    Session timeouts and permission scopes are derived from this role
    downstream (SCRUM-17 / SCRUM-18). ``senco_admin`` and ``other_admin``
    are kept distinct because they carry different session timeouts.
    """

    STUDENT = "student"
    TEACHER = "teacher"
    SENCO_ADMIN = "senco_admin"
    OTHER_ADMIN = "other_admin"
    PARENT_GUARDIAN = "parent_guardian"


class AuthMethod(StrEnum):
    """How an account (or a school by default) authenticates."""

    EMAIL_PASSWORD = "email_password"
    PIN = "pin"
    SSO = "sso"


class SsoProvider(StrEnum):
    MICROSOFT = "microsoft"
    GOOGLE = "google"


class SsoFirstUseDestination(StrEnum):
    OBSERVED_INTERACTION = "observed_interaction"
    HOME_DASHBOARD = "home_dashboard"


class RosterSyncStatus(StrEnum):
    COMPLETED = "completed"
    PARTIAL_MANUAL_REVIEW = "partial_manual_review"
    FAILED = "failed"


class RosterSyncIssueStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"


class SsoConnectionStatus(StrEnum):
    """Health of a school's live SSO integration.

    ``NEEDS_ATTENTION`` is a recovery state, not an error state: sign-in and
    rostering keep working on cached data, and the admin is asked to
    reauthorise. ``DISCONNECTED`` is always deliberate and never deletes
    accounts.
    """

    CONNECTED = "connected"
    NEEDS_ATTENTION = "needs_attention"
    DISCONNECTED = "disconnected"


class UserStatus(StrEnum):
    """Lifecycle state of an account."""

    ACTIVE = "active"
    INVITED = "invited"
    DEACTIVATED = "deactivated"


class SchoolEnrollmentBand(StrEnum):
    """Commercial enrollment banding for a school.

    Assumption (not fixed by the ticket): named size tiers. Confirm the exact
    band boundaries against Backend Architecture Section 2 in review.
    """

    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"
    VERY_LARGE = "very_large"


class ConsentStatus(StrEnum):
    """Whether a consent record has been confirmed by an administrator."""

    PENDING = "pending"
    CONFIRMED = "confirmed"


class ConsentType(StrEnum):
    """What a consent record grants.

    Assumption (not enumerated by the ticket): derived from the legacy
    per-school consent flags (data protection, camera, offline access).
    """

    DATA_PROCESSING = "data_processing"
    CAMERA = "camera"
    OFFLINE_STORAGE = "offline_storage"


class ConsentMethod(StrEnum):
    """How a consent confirmation was obtained.

    Assumption (not enumerated by the ticket). Confirm against the consent
    collection design in SCRUM-20 during review.
    """

    WRITTEN = "written"
    VERBAL = "verbal"
    EMAIL = "email"
    DIGITAL = "digital"


class NotificationCategory(StrEnum):
    """Notification streams a user can mute independently.

    Enumerated so a typo is rejected rather than silently creating a phantom
    preference row that mutes nothing. Adding a stream here is a one-line
    change; a category absent from this list is a 422, not a silent no-op.
    """

    ASSIGNMENTS = "assignments"
    MESSAGES = "messages"
    ATTENTION = "attention"
    REPORTS = "reports"
    CONSENT = "consent"
    BILLING = "billing"
    ACCOUNT = "account"


class NotificationType(StrEnum):
    """What a notification is about.

    Drives the icon and the navigation target, so the console needs the set to
    be closed rather than guessing from a free string.
    """

    ATTENTION_SUMMARY = "attention_summary"
    MODALITY_SHIFT = "modality_shift"
    PIN_RESET_REQUESTED = "pin_reset_requested"


class MessageRecipientType(StrEnum):
    """Whether a thread addresses one student or a whole class."""

    STUDENT = "student"
    CLASS = "class"


class ClassSource(StrEnum):
    """How a class came to exist."""

    MANUAL = "manual"
    ROSTER_SYNC = "roster_sync"


class InvitationDeliveryStatus(StrEnum):
    """Whether an invitation email actually went out.

    ``email_not_configured`` is deliberately distinct from ``sent``: the
    invitation exists and its link is valid, but nobody was emailed, so the
    caller has to deliver it another way.
    """

    NOT_REQUESTED = "not_requested"
    SENT = "sent"
    EMAIL_NOT_CONFIGURED = "email_not_configured"
