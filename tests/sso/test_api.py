from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from nevo.api.auth import authenticated_principal
from nevo.api.sso import router
from nevo.auth.entities import AuthPrincipal, IssuedSession
from nevo.domain.accounts.vocabulary import (
    RosterSyncStatus,
    SsoFirstUseDestination,
    SsoProvider,
)
from nevo.permissions.entities import PermissionSnapshot
from nevo.sso.entities import RosterSyncResult, SsoLoginResult, SsoStart
from nevo.sso.service import SsoService

USER_ID = UUID("00000000-0000-4000-8000-000000000001")
ISSUE_ID = UUID("00000000-0000-4000-8000-000000000002")


class FakeSsoService(SsoService):
    def __init__(self) -> None:
        self.callback_args = None

    async def start(self, *, school_slug, provider):
        return SsoStart(
            authorization_url=f"https://provider.example/{provider.value}",
            school_entry_url=f"https://nevo.app/{school_slug}",
        )

    async def callback(self, *, school_slug, provider, code):
        self.callback_args = (school_slug, provider, code)
        return SsoLoginResult(
            session=IssuedSession(
                access_token="token",
                token_type="bearer",
                expires_at=datetime(2026, 7, 23, tzinfo=UTC),
                user_id=USER_ID,
                role="student",
                replaced_session=False,
            ),
            destination=SsoFirstUseDestination.HOME_DASHBOARD,
        )

    async def sync_roster(self, *, school_slug, provider):
        return RosterSyncResult(
            status=RosterSyncStatus.PARTIAL_MANUAL_REVIEW,
            imported_students=10,
            imported_teachers=2,
            missing_teacher_class_mappings=1,
            issue_ids=(ISSUE_ID,),
        )


def client_for() -> tuple[TestClient, FakeSsoService]:
    principal = AuthPrincipal(user_id=uuid4(), role="other_admin", session_id=uuid4())
    service = FakeSsoService()
    app = FastAPI()
    app.state.sso_service = service
    app.dependency_overrides[authenticated_principal] = lambda: principal
    app.dependency_overrides.clear()
    app.dependency_overrides[authenticated_principal] = lambda: principal
    # Bypass full permission repository; route logic itself is covered here.
    from nevo.api.sso import ItSsoDependency

    dependency = ItSsoDependency.__metadata__[0].dependency
    app.dependency_overrides[dependency] = lambda: PermissionSnapshot(
        user_id=principal.user_id,
        school_id=uuid4(),
        role=principal.role,
        status="active",
        school_auth_method="sso",
        assigned_scopes=frozenset(),
    )
    app.include_router(router)
    return TestClient(app), service


def test_sso_start_endpoint() -> None:
    client, _ = client_for()

    response = client.get("/api/v1/schools/nevo-school/sso/google/start")

    assert response.status_code == 200
    assert response.json()["school_entry_url"] == "https://nevo.app/nevo-school"


def test_sso_callback_endpoint_validates_state() -> None:
    client, service = client_for()

    response = client.get(
        "/api/v1/auth/sso/google/callback",
        params={"code": "abc", "state": "nevo-school:google"},
    )

    assert response.status_code == 200
    assert response.json()["destination"] == "home_dashboard"
    assert service.callback_args == ("nevo-school", SsoProvider.GOOGLE, "abc")


def test_sso_roster_sync_endpoint() -> None:
    client, _ = client_for()

    response = client.post("/api/v1/schools/nevo-school/sso/google/roster-sync")

    assert response.status_code == 200
    assert response.json()["missing_teacher_class_mappings"] == 1
    assert response.json()["issue_ids"] == [str(ISSUE_ID)]
