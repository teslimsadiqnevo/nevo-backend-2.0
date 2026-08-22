from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from nevo.api.auth import authenticated_principal
from nevo.api.billing import router
from nevo.auth.entities import AuthPrincipal
from nevo.billing.entities import (
    BillingContactRecord,
    InvoiceRecord,
    PaymentMethodRecord,
    SubscriptionRecord,
    UpcomingCharge,
)
from nevo.billing.service import BillingService
from nevo.domain.accounts.vocabulary import SchoolEnrollmentBand
from nevo.domain.billing.vocabulary import (
    InvoiceStatus,
    PaymentMethodType,
    SubscriptionTier,
)
from nevo.permissions.entities import PermissionSnapshot

USER_ID = uuid4()
SCHOOL_ID = uuid4()


class FakeBillingService(BillingService):
    def __init__(self) -> None:
        self.payment_update = None
        self.contact_update = None

    async def subscription(self, school_id):
        assert school_id == SCHOOL_ID
        return SubscriptionRecord(
            school_id=school_id,
            school_name="Nevo School",
            subscription_tier=SubscriptionTier.PREMIUM,
            student_count_band=SchoolEnrollmentBand.MEDIUM,
            contract_value=Decimal("1200000.00"),
            contract_start=datetime(2026, 1, 1, tzinfo=UTC),
            contract_end=datetime(2026, 9, 15, tzinfo=UTC),
            renewal_banner_visible=True,
            renewal_message="Your current contract renews on 2026-09-15.",
            billing_contact=_contact(),
            payment_method=_payment_method(),
        )

    async def invoices(self, *, school_id, date_from, date_to, status):
        assert school_id == SCHOOL_ID
        assert status is InvoiceStatus.PAID
        return (
            InvoiceRecord(
                id=uuid4(),
                invoice_number="NEVO-2026-001",
                issued_at=date(2026, 1, 1),
                amount=Decimal("1200000.00"),
                status=InvoiceStatus.PAID,
                due_at=date(2026, 1, 31),
                paid_at=datetime(2026, 1, 15, tzinfo=UTC),
                pdf_url="https://cdn.nevo.app/invoices/NEVO-2026-001.pdf",
            ),
        )

    async def upcoming(self, school_id):
        assert school_id == SCHOOL_ID
        return UpcomingCharge(
            invoice_id=uuid4(),
            invoice_number="NEVO-2026-002",
            due_at=date(2026, 9, 15),
            amount=Decimal("1200000.00"),
            status=InvoiceStatus.PENDING,
            renewal_banner_visible=True,
            renewal_message="Your current contract renews on 2026-09-15.",
        )

    async def update_payment_method(self, **kwargs):
        self.payment_update = kwargs
        return _payment_method(last_four=kwargs["update_data"].last_four)

    async def update_billing_contact(self, **kwargs):
        self.contact_update = kwargs
        return _contact(email=kwargs["update_data"].email)


def _contact(email: str = "finance@school.example") -> BillingContactRecord:
    return BillingContactRecord(
        id=uuid4(),
        email=email,
        phone="+2348000000000",
        address_line1="1 Learning Street",
        address_line2=None,
        city="Lagos",
        region="Lagos",
        postal_code=None,
        country="Nigeria",
    )


def _payment_method(last_four: str = "4242") -> PaymentMethodRecord:
    return PaymentMethodRecord(
        id=uuid4(),
        method_type=PaymentMethodType.CARD,
        display_name="Visa ending 4242",
        last_four=last_four,
        card_brand="visa",
        expiry_month=12,
        expiry_year=2028,
        bank_name=None,
        account_holder_name=None,
        updated_at=datetime(2026, 8, 22, tzinfo=UTC),
    )


def client_for(
    *,
    school_id=SCHOOL_ID,
) -> tuple[TestClient, FakeBillingService]:
    principal = AuthPrincipal(user_id=USER_ID, role="other_admin", session_id=uuid4())
    service = FakeBillingService()
    app = FastAPI()
    app.state.billing_service = service
    app.dependency_overrides[authenticated_principal] = lambda: principal
    from nevo.api.billing import BillingScopeDependency

    dependency = BillingScopeDependency.__metadata__[0].dependency
    app.dependency_overrides[dependency] = lambda: PermissionSnapshot(
        user_id=principal.user_id,
        school_id=school_id,
        role=principal.role,
        status="active",
        school_auth_method="email_password",
        assigned_scopes=frozenset(),
    )
    app.include_router(router)
    return TestClient(app), service


def test_subscription_endpoint_returns_contract_and_masked_payment_details() -> None:
    client, _ = client_for()

    response = client.get("/api/billing/subscription")

    assert response.status_code == 200
    body = response.json()
    assert body["subscriptionTier"] == "premium"
    assert body["contractValue"] == "1200000.00"
    assert body["renewalBannerVisible"] is True
    assert body["paymentMethod"]["lastFour"] == "4242"
    assert "processor" not in body["paymentMethod"]


def test_invoice_history_endpoint_filters_by_status() -> None:
    client, _ = client_for()

    response = client.get(
        "/api/billing/invoices",
        params={"status": "paid", "dateFrom": "2026-01-01"},
    )

    assert response.status_code == 200
    assert response.json()[0]["invoiceNumber"] == "NEVO-2026-001"
    assert response.json()[0]["pdfUrl"].endswith(".pdf")


def test_upcoming_charge_endpoint_returns_next_invoice() -> None:
    client, _ = client_for()

    response = client.get("/api/billing/upcoming")

    assert response.status_code == 200
    assert response.json()["invoiceNumber"] == "NEVO-2026-002"
    assert response.json()["renewalBannerVisible"] is True


def test_payment_method_update_accepts_only_masked_details() -> None:
    client, service = client_for()

    response = client.put(
        "/api/billing/payment-method",
        json={
            "methodType": "card",
            "displayName": "Visa ending 1111",
            "lastFour": "1111",
            "cardBrand": "visa",
            "expiryMonth": 12,
            "expiryYear": 2028,
            "processorPaymentMethodRef": "pm_safe_reference",
        },
    )

    assert response.status_code == 200
    assert response.json()["lastFour"] == "1111"
    assert service.payment_update["actor_user_id"] == USER_ID


def test_billing_contact_update_keeps_finance_contact_separate() -> None:
    client, service = client_for()

    response = client.put(
        "/api/billing/billing-contact",
        json={
            "email": "accounts@school.example",
            "phone": "+2348111111111",
            "addressLine1": "2 Finance Road",
            "city": "Abuja",
            "country": "Nigeria",
        },
    )

    assert response.status_code == 200
    assert response.json()["email"] == "accounts@school.example"
    assert service.contact_update["actor_user_id"] == USER_ID


def test_billing_endpoints_require_school_context() -> None:
    client, _ = client_for(school_id=None)

    response = client.get("/api/billing/subscription")

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "missing_school_context"
