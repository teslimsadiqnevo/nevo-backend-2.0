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
