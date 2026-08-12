from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from nevo.api.auth import authenticated_principal
from nevo.api.sso import router
from nevo.auth.entities import AuthPrincipal, IssuedSession
from nevo.domain.accounts.vocabulary import (
    RosterSyncStatus,
    SsoConnectionStatus,
    SsoFirstUseDestination,
    SsoProvider,
)
from nevo.permissions.entities import PermissionSnapshot
from nevo.sso.entities import (
    RosterSyncHistory,
    RosterSyncIssueView,
    RosterSyncResult,
    RosterSyncRunView,
    SsoConnectionHealth,
    SsoDisconnection,
    SsoLoginResult,
    SsoReauthorisation,
    SsoStart,
)
from nevo.sso.service import SSO_DATA_FLOW, SsoDisconnectedError, SsoService

USER_ID = UUID("00000000-0000-4000-8000-000000000001")
ISSUE_ID = UUID("00000000-0000-4000-8000-000000000002")
RUN_ID = UUID("00000000-0000-4000-8000-000000000003")


class FakeSsoService(SsoService):
    def __init__(self) -> None:
        self.callback_args = None
        self.configured = True
        self.disconnected = False
        self.manual_sync_actor: UUID | None = None
        self.disconnected_by: UUID | None = None
        self.history_window_days: int | None = None

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

    async def connection_health(self, school_id):
        if not self.configured:
            raise LookupError("SSO is not configured for this school")
        return SsoConnectionHealth(
            school_id=school_id,
            provider=SsoProvider.GOOGLE,
            status=SsoConnectionStatus.NEEDS_ATTENTION,
            school_url_slug="nevo-school",
            school_entry_url="https://nevo.app/nevo-school",
            data_flow=SSO_DATA_FLOW,
            last_connection_error="Directory permission was withdrawn.",
            connection_checked_at=datetime(2026, 7, 23, tzinfo=UTC),
            reauthorised_at=None,
            last_successful_sync_at=datetime(2026, 7, 22, tzinfo=UTC),
            next_scheduled_sync_at=datetime(2026, 7, 24, tzinfo=UTC),
            disconnected_at=None,
        )

    async def sync_history(self, *, school_id, window_days=30):
        self.history_window_days = window_days
        return RosterSyncHistory(
            school_id=school_id,
            window_days=window_days,
            successful_runs=4,
            failed_runs=1,
            runs=(
                RosterSyncRunView(
                    id=RUN_ID,
                    provider=SsoProvider.GOOGLE,
                    status=RosterSyncStatus.PARTIAL_MANUAL_REVIEW,
                    imported_students=10,
                    imported_teachers=2,
                    missing_teacher_class_mappings=1,
                    failure_reason=None,
                    triggered_manually=True,
                    started_at=datetime(2026, 7, 22, tzinfo=UTC),
                    completed_at=datetime(2026, 7, 22, tzinfo=UTC),
                    issues=(
                        RosterSyncIssueView(
                            id=ISSUE_ID,
                            external_reference="missing-class",
                            description="Teacher-class mapping was not found.",
                            resolution_hint="Create the class in Nevo.",
                        ),
                    ),
                ),
            ),
        )

    async def sync_roster_for_school(self, *, school_id, triggered_by_user_id):
        if not self.configured:
            raise LookupError("SSO is not configured for this school")
        if self.disconnected:
            raise SsoDisconnectedError(
                "Single sign-on is disconnected for this school."
            )
        self.manual_sync_actor = triggered_by_user_id
        return RosterSyncResult(
            status=RosterSyncStatus.COMPLETED,
            imported_students=10,
            imported_teachers=2,
            missing_teacher_class_mappings=0,
            issue_ids=(),
        )

    async def reauthorise(self, school_id):
        if not self.configured:
            raise LookupError("SSO is not configured for this school")
        return SsoReauthorisation(
            provider=SsoProvider.GOOGLE,
            authorization_url="https://provider.example/auth?state=x",
            school_entry_url="https://nevo.app/nevo-school",
        )

    async def disconnect(self, *, school_id, disconnected_by_user_id):
        if not self.configured:
            raise LookupError("SSO is not configured for this school")
        self.disconnected_by = disconnected_by_user_id
        return SsoDisconnection(
            school_id=school_id,
            provider=SsoProvider.GOOGLE,
            disconnected_at=datetime(2026, 7, 23, tzinfo=UTC),
            retained_user_count=42,
        )


def client_for(
    *,
    configured: bool = True,
) -> tuple[TestClient, FakeSsoService, UUID]:
    principal = AuthPrincipal(user_id=USER_ID, role="other_admin", session_id=uuid4())
    school_id = uuid4()
    service = FakeSsoService()
    service.configured = configured
    app = FastAPI()
    app.state.sso_service = service
    app.dependency_overrides[authenticated_principal] = lambda: principal
    # Bypass full permission repository; route logic itself is covered here.
    from nevo.api.sso import ItSsoDependency

    dependency = ItSsoDependency.__metadata__[0].dependency
    app.dependency_overrides[dependency] = lambda: PermissionSnapshot(
        user_id=principal.user_id,
        school_id=school_id,
        role=principal.role,
        status="active",
        school_auth_method="sso",
        assigned_scopes=frozenset(),
    )
    app.include_router(router)
    return TestClient(app), service, school_id


def test_sso_start_endpoint() -> None:
    client, _, _ = client_for()

    response = client.get("/api/v1/schools/nevo-school/sso/google/start")

    assert response.status_code == 200
    assert response.json()["school_entry_url"] == "https://nevo.app/nevo-school"


def test_sso_callback_endpoint_validates_state() -> None:
    client, service, _ = client_for()

    response = client.get(
        "/api/v1/auth/sso/google/callback",
        params={"code": "abc", "state": "nevo-school:google"},
    )

    assert response.status_code == 200
    assert response.json()["destination"] == "home_dashboard"
    assert service.callback_args == ("nevo-school", SsoProvider.GOOGLE, "abc")


def test_sso_roster_sync_endpoint() -> None:
    client, _, _ = client_for()

    response = client.post("/api/v1/schools/nevo-school/sso/google/roster-sync")

    assert response.status_code == 200
    assert response.json()["missing_teacher_class_mappings"] == 1
    assert response.json()["issue_ids"] == [str(ISSUE_ID)]


def test_admin_status_reports_health_and_data_flow() -> None:
    client, _, _ = client_for()

    response = client.get("/api/v1/admin/sso/status")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "needs_attention"
    assert body["last_connection_error"] == "Directory permission was withdrawn."
    assert body["last_successful_sync_at"] is not None
    assert body["next_scheduled_sync_at"] is not None
    assert [item["key"] for item in body["data_flow"]] == [
        category.key for category in SSO_DATA_FLOW
    ]


def test_admin_status_is_404_when_sso_was_never_configured() -> None:
    client, _, _ = client_for(configured=False)

    response = client.get("/api/v1/admin/sso/status")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "sso_not_configured"


def test_admin_sync_history_explains_failed_events() -> None:
    client, _, _ = client_for()

    response = client.get("/api/v1/admin/sso/roster-sync-history")

    assert response.status_code == 200
    body = response.json()
    assert body["successful_runs"] == 4
    assert body["failed_runs"] == 1
    issue = body["runs"][0]["issues"][0]
    assert issue["resolution_hint"] == "Create the class in Nevo."
    assert body["runs"][0]["triggered_manually"] is True


def test_admin_sync_history_window_is_bounded() -> None:
    client, service, _ = client_for()

    assert client.get(
        "/api/v1/admin/sso/roster-sync-history",
        params={"window_days": 7},
    ).status_code == 200
    assert service.history_window_days == 7

    for invalid in (0, 366):
        response = client.get(
            "/api/v1/admin/sso/roster-sync-history",
            params={"window_days": invalid},
        )
        assert response.status_code == 422


def test_admin_manual_sync_is_attributed_to_the_actor() -> None:
    client, service, _ = client_for()

    response = client.post("/api/v1/admin/sso/roster-sync")

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert service.manual_sync_actor == USER_ID


def test_admin_manual_sync_conflicts_while_disconnected() -> None:
    client, service, _ = client_for()
    service.disconnected = True

    response = client.post("/api/v1/admin/sso/roster-sync")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "sso_disconnected"


def test_admin_reauthorise_returns_a_fresh_provider_url() -> None:
    client, _, _ = client_for()

    response = client.post("/api/v1/admin/sso/reauthorise")

    assert response.status_code == 200
    assert response.json()["authorization_url"].startswith("https://provider.example")


def test_admin_disconnect_requires_confirmation() -> None:
    client, service, _ = client_for()

    response = client.post(
        "/api/v1/admin/sso/disconnect",
        json={"confirm": False},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "confirmation_required"
    assert service.disconnected_by is None


def test_admin_disconnect_keeps_accounts_and_reports_the_count() -> None:
    client, service, _ = client_for()

    response = client.post(
        "/api/v1/admin/sso/disconnect",
        json={"confirm": True},
    )

    assert response.status_code == 200
    assert response.json()["retained_user_count"] == 42
    assert service.disconnected_by == USER_ID


def test_admin_endpoints_require_a_school_context() -> None:
    """A platform-level admin has no school to act on."""
    principal = AuthPrincipal(user_id=USER_ID, role="other_admin", session_id=uuid4())
    app = FastAPI()
    app.state.sso_service = FakeSsoService()
    app.dependency_overrides[authenticated_principal] = lambda: principal
    from nevo.api.sso import ItSsoDependency

    dependency = ItSsoDependency.__metadata__[0].dependency
    app.dependency_overrides[dependency] = lambda: PermissionSnapshot(
        user_id=principal.user_id,
        school_id=None,
        role=principal.role,
        status="active",
        school_auth_method="sso",
        assigned_scopes=frozenset(),
    )
    app.include_router(router)
    client = TestClient(app)

    response = client.get("/api/v1/admin/sso/status")

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "missing_school_context"
