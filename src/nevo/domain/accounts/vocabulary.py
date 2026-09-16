from enum import StrEnum


class InvitableRole(StrEnum):
    """The roles a school administrator can invite into their school.

    A subset of UserRole on purpose. Administrators are created by school
    registration, and parents by the consent link - the only place the child
    they belong to is known.
    """

    STUDENT = "student"
    TEACHER = "teacher"


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
    #: Started, and still walking the provider's pages.
    RUNNING = "running"
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
    """Frontend-visible lifecycle of required learner consent."""

    NOT_SENT = "not_sent"
    PENDING = "pending"
    CONFIRMED = "confirmed"
    WITHDRAWN = "withdrawn"


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
    ADMIN_WELCOME = "admin_welcome"
    CONSENT_ACTION_REQUIRED = "consent_action_required"
    ROSTER_SYNC_COMPLETED = "roster_sync_completed"
    ROSTER_SYNC_NEEDS_ATTENTION = "roster_sync_needs_attention"
    INVOICE_ISSUED = "invoice_issued"
    SSO_NEEDS_ATTENTION = "sso_needs_attention"


#: Which preference switch governs each kind of notification.
#:
#: A teacher could mute a category and still receive everything in it, because
#: nothing on a notification said which category it belonged to - the
#: preference had seven switches and no notification could be matched to any of
#: them. Derived from the type rather than stored beside it, so the two cannot
#: disagree and no existing row needs correcting.
NOTIFICATION_CATEGORY_BY_TYPE: dict[NotificationType, NotificationCategory] = {}


def notification_category(
    notification_type: NotificationType | str | None,
) -> NotificationCategory | None:
    """The category a notification belongs to, or None if it belongs to none.

    None is a real answer, not a failure: a notification of a kind this mapping
    does not know cannot be muted by any switch the settings screen offers, and
    saying so is more useful than picking a category it does not belong to.
    """

    if notification_type is None:
        return None
    try:
        key = NotificationType(notification_type)
    except ValueError:
        return None
    return NOTIFICATION_CATEGORY_BY_TYPE.get(key)


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


NOTIFICATION_CATEGORY_BY_TYPE.update(
    {
        NotificationType.ATTENTION_SUMMARY: NotificationCategory.ATTENTION,
        NotificationType.MODALITY_SHIFT: NotificationCategory.ATTENTION,
        NotificationType.PIN_RESET_REQUESTED: NotificationCategory.ACCOUNT,
        NotificationType.ADMIN_WELCOME: NotificationCategory.ACCOUNT,
        NotificationType.CONSENT_ACTION_REQUIRED: NotificationCategory.CONSENT,
        NotificationType.ROSTER_SYNC_COMPLETED: NotificationCategory.REPORTS,
        NotificationType.ROSTER_SYNC_NEEDS_ATTENTION: NotificationCategory.REPORTS,
        NotificationType.SSO_NEEDS_ATTENTION: NotificationCategory.ACCOUNT,
        NotificationType.INVOICE_ISSUED: NotificationCategory.BILLING,
    }
)
