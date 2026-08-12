from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from nevo.auth.entities import IssuedSession
from nevo.domain.accounts.vocabulary import (
    RosterSyncStatus,
    SsoConnectionStatus,
    SsoFirstUseDestination,
    SsoProvider,
    UserRole,
)


@dataclass(frozen=True, slots=True)
class SsoSchoolConfig:
    school_id: UUID
    school_url_slug: str
    provider: SsoProvider
    client_id: str
    tenant_id: str | None = None
    hosted_domain: str | None = None


@dataclass(frozen=True, slots=True)
class SsoProviderIdentity:
    provider: SsoProvider
    external_id: str
    email: str
    first_name: str | None
    last_name: str | None
    role: UserRole


@dataclass(frozen=True, slots=True)
class SsoStart:
    authorization_url: str
    school_entry_url: str


@dataclass(frozen=True, slots=True)
class SsoLoginResult:
    session: IssuedSession
    destination: SsoFirstUseDestination


@dataclass(frozen=True, slots=True)
class RosterAccount:
    external_id: str
    email: str
    first_name: str | None
    last_name: str | None
    role: UserRole
    class_external_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RosterSyncBatch:
    students: tuple[RosterAccount, ...]
    teachers: tuple[RosterAccount, ...]


@dataclass(frozen=True, slots=True)
class RosterSyncResult:
    status: RosterSyncStatus
    imported_students: int
    imported_teachers: int
    missing_teacher_class_mappings: int
    issue_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class SsoDataFlowCategory:
    """One category of data Nevo ingests from the identity provider.

    Enumerated on the backend rather than written into the frontend so the
    transparency notice cannot drift from what the roster sync actually
    reads.
    """

    key: str
    description: str
    purpose: str


@dataclass(frozen=True, slots=True)
class SsoConnectionHealth:
    school_id: UUID
    provider: SsoProvider
    status: SsoConnectionStatus
    school_url_slug: str
    # Composed by the service, which owns the base URLs and the copy; the
    # repository leaves these empty.
    school_entry_url: str
    data_flow: tuple["SsoDataFlowCategory", ...]
    last_connection_error: str | None
    connection_checked_at: datetime | None
    reauthorised_at: datetime | None
    last_successful_sync_at: datetime | None
    next_scheduled_sync_at: datetime | None
    disconnected_at: datetime | None


@dataclass(frozen=True, slots=True)
class RosterSyncIssueView:
    id: UUID
    external_reference: str
    description: str
    resolution_hint: str | None


@dataclass(frozen=True, slots=True)
class RosterSyncRunView:
    id: UUID
    provider: SsoProvider
    status: RosterSyncStatus
    imported_students: int
    imported_teachers: int
    missing_teacher_class_mappings: int
    failure_reason: str | None
    triggered_manually: bool
    started_at: datetime
    completed_at: datetime | None
    issues: tuple[RosterSyncIssueView, ...]


@dataclass(frozen=True, slots=True)
class RosterSyncHistory:
    school_id: UUID
    window_days: int
    successful_runs: int
    failed_runs: int
    runs: tuple[RosterSyncRunView, ...]


@dataclass(frozen=True, slots=True)
class SsoReauthorisation:
    provider: SsoProvider
    authorization_url: str
    school_entry_url: str


@dataclass(frozen=True, slots=True)
class SsoDisconnection:
    school_id: UUID
    provider: SsoProvider
    disconnected_at: datetime
    # Stated explicitly so the confirmation copy cannot overpromise.
    retained_user_count: int
