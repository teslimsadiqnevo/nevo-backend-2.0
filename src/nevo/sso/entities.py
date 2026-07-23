from dataclasses import dataclass
from uuid import UUID

from nevo.auth.entities import IssuedSession
from nevo.domain.accounts.vocabulary import (
    RosterSyncStatus,
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
