from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import Response

from nevo.api import frontend_unblockers
from nevo.api.billing import UpcomingChargeResponse
from nevo.api.permissions import public_permission_error
from nevo.billing.entities import UpcomingCharge
from nevo.db.models.account import User
from nevo.db.models.permission import Admin, LearningSupportGrant
from nevo.domain.accounts.vocabulary import UserRole, UserStatus
from nevo.domain.billing.vocabulary import InvoiceStatus, PricingCurrency
from nevo.domain.permissions.vocabulary import AdminAccessLevel, PermissionScope
from nevo.main import app
from nevo.parents.subject_progress import build_window
from nevo.parents.subject_reader import child_subject_progress
from nevo.permissions.errors import LastSeniorAdminError
from nevo.permissions.repositories import SqlAlchemyPermissionRepository


def test_schools_without_terms_default_to_since_setup():
    now = datetime(2026, 10, 14, 12, tzinfo=UTC)
    result = build_window(
        now=now,
        starts_on=None,
        term_starts=[],
        breaks=[],
        setup_at=datetime(2026, 9, 1, tzinfo=UTC),
    )
    assert result.kind == "since_setup"
    assert result.starts_on == date(2026, 9, 1)
    assert result.ends_on == date(2026, 10, 14)
    historical = build_window(
        now=now,
        starts_on=date(2026, 10, 1),
        term_starts=[],
        breaks=[],
        setup_at=datetime(2026, 9, 1, tzinfo=UTC),
    )
    assert historical.kind == "week"


@pytest.mark.asyncio
async def test_quiet_subject_returns_lifetime_mastery_and_last_lesson():
    now = datetime(2026, 10, 14, 12, tzinfo=UTC)
    school_id = uuid4()
    school = SimpleNamespace(
        academic_config={"term_start_dates": ["2026-09-01"]}, created_at=now - timedelta(days=100)
    )
    last_lesson = now - timedelta(days=10)
    results = [
        [(uuid4(), "Mathematics", "Mathematics")],
        [],
        [("Mathematics", last_lesson)],
        [
            ("Mathematics", "Fractions", Decimal("0.95"), now - timedelta(days=20), 3),
            ("Mathematics", "Ratios", Decimal("0.90"), now - timedelta(days=20), 4),
        ],
    ]
    execute = AsyncMock(
        side_effect=[SimpleNamespace(all=lambda rows=rows: rows) for rows in results]
    )
    session = SimpleNamespace(
        scalar=AsyncMock(return_value=school_id),
        get=AsyncMock(return_value=school),
        execute=execute,
    )
    result = await child_subject_progress(session, student_id=uuid4(), now=now)
    row = result.subjects[0]
    assert row.mastered_so_far == 2
    assert row.mastered_before_window == 2
    assert row.mastered_this_window == ()
    assert row.last_lesson_at == last_lesson


def test_upcoming_charge_uses_real_student_and_vat_lines():
    charge = UpcomingCharge(
        invoice_id=uuid4(),
        invoice_number="QA-1",
        due_at=date(2026, 11, 1),
        amount=Decimal("10750"),
        status=InvoiceStatus.PENDING,
        renewal_banner_visible=False,
        renewal_message=None,
        currency=PricingCurrency.USD,
        student_count=100,
        per_student_rate=Decimal("100"),
        total_before_vat=Decimal("10000"),
        vat_amount=Decimal("750"),
        vat_rate=Decimal("7.5"),
    )
    result = UpcomingChargeResponse.from_record(charge)
    assert [line.kind for line in result.line_items] == ["subscription", "vat"]
    assert sum(line.amount for line in result.line_items) == charge.amount
    assert result.line_items[0].quantity == 100
    assert result.line_items[0].unit_amount == Decimal("100")
    assert result.line_items[1].percentage_rate == Decimal("7.5")
    assert all(line.currency == PricingCurrency.USD for line in result.line_items)


def test_legacy_invoice_does_not_invent_a_breakdown():
    charge = UpcomingCharge(
        invoice_id=uuid4(),
        invoice_number="OLD",
        due_at=date(2026, 11, 1),
        amount=Decimal("100"),
        status=InvoiceStatus.PENDING,
        renewal_banner_visible=False,
        renewal_message=None,
    )
    assert UpcomingChargeResponse.from_record(charge).line_items == []


@pytest.mark.asyncio
async def test_last_active_senior_cannot_be_demoted():
    admin = SimpleNamespace(access_level=AdminAccessLevel.SENIOR)
    user = SimpleNamespace(status=UserStatus.ACTIVE)
    session = SimpleNamespace(
        get=AsyncMock(return_value=object()),
        execute=AsyncMock(return_value=SimpleNamespace(one_or_none=lambda: (admin, user))),
        scalar=AsyncMock(return_value=None),
    )
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=session)
    context.__aexit__ = AsyncMock(return_value=False)
    factory = SimpleNamespace(begin=lambda: context)
    repository = SqlAlchemyPermissionRepository(factory)
    with pytest.raises(LastSeniorAdminError):
        await repository.set_admin_access_level(
            school_id=uuid4(), target_user_id=uuid4(), access_level=AdminAccessLevel.STANDARD
        )
    assert admin.access_level is AdminAccessLevel.SENIOR
    error = public_permission_error(LastSeniorAdminError())
    assert error.status_code == 409
    assert error.detail["code"] == "last_senior_admin"


@pytest.mark.asyncio
async def test_demotion_preserves_scopes_and_reports_learning_support(monkeypatch):
    school_id, user_id, granter_id = uuid4(), uuid4(), uuid4()
    admin = Admin(
        id=uuid4(), school_id=school_id, user_id=user_id, access_level=AdminAccessLevel.SENIOR
    )
    user = User(id=user_id, role=UserRole.OTHER_ADMIN, status=UserStatus.ACTIVE)
    granter = User(id=granter_id, first_name="Senior", last_name="Admin")
    grant = LearningSupportGrant(
        holder_user_id=user_id,
        school_id=school_id,
        granted_by_user_id=granter_id,
        granted_at=datetime.now(UTC),
    )
    session = SimpleNamespace(
        get=AsyncMock(return_value=object()),
        flush=AsyncMock(),
        execute=AsyncMock(
            side_effect=[
                SimpleNamespace(one_or_none=lambda: (admin, user)),
                SimpleNamespace(one_or_none=lambda: (grant, granter)),
            ]
        ),
        scalar=AsyncMock(return_value=granter_id),
    )
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=session)
    context.__aexit__ = AsyncMock(return_value=False)
    repository = SqlAlchemyPermissionRepository(SimpleNamespace(begin=lambda: context))
    scopes = frozenset({PermissionScope.BILLING})
    monkeypatch.setattr(repository, "_active_scopes_for_update", AsyncMock(return_value=scopes))
    result = await repository.set_admin_access_level(
        school_id=school_id, target_user_id=user_id, access_level=AdminAccessLevel.STANDARD
    )
    assert result.access_level is AdminAccessLevel.STANDARD
    assert result.scopes == scopes
    assert result.learning_support is True
    assert result.learning_support_granted_by_name == "Senior Admin"


def test_closeout_contracts_are_published():
    spec = app.openapi()
    parameters = {p["name"] for p in spec["paths"]["/api/v1/escalations"]["get"]["parameters"]}
    assert {"openOnly", "limit", "offset"} <= parameters
    assert "post" in spec["paths"]["/api/v1/admin/team/{target_user_id}/demote-standard"]
    fields = spec["components"]["schemas"]["SubjectProgressResponse"]["properties"]
    assert {"masteredSoFar", "lastLessonAt"} <= set(fields)
    assert "teacherDetailsFound" in spec["components"]["schemas"]["OnboardingState"]["properties"]


@pytest.mark.asyncio
async def test_open_concern_count_is_not_capped_at_one_page(monkeypatch):
    actor = SimpleNamespace(school_id=uuid4(), role=UserRole.OTHER_ADMIN)
    monkeypatch.setattr(frontend_unblockers, "require_school_actor", AsyncMock(return_value=actor))
    session = SimpleNamespace(
        scalar=AsyncMock(return_value=137),
        execute=AsyncMock(return_value=SimpleNamespace(all=lambda: [])),
    )
    response = Response()
    rows = await frontend_unblockers.list_escalations(
        SimpleNamespace(), session, response, open_only=True, limit=50, offset=0
    )
    assert rows == []
    assert response.headers["X-Total-Count"] == "137"
    assert response.headers["X-Has-More"] == "true"
    counted_query = str(session.scalar.call_args.args[0])
    assert "acknowledged_at IS NULL" in counted_query
    assert "LIMIT" not in counted_query
