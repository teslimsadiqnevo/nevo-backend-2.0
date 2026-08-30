from datetime import date, datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from sqlalchemy import select

from nevo.api.dependencies import DatabaseSession
from nevo.api.permissions import RequireScope
from nevo.billing.entities import (
    BillingContactRecord,
    BillingContactUpdate,
    InvoiceRecord,
    PaymentMethodRecord,
    PaymentMethodUpdate,
    SubscriptionRecord,
    UpcomingCharge,
)
from nevo.billing.errors import (
    BillingError,
    BillingNotFoundError,
    BillingPaymentMethodError,
    BillingSchoolContextError,
)
from nevo.billing.service import BillingService
from nevo.db.models.account import School
from nevo.db.models.billing import Invoice
from nevo.domain.accounts.vocabulary import SchoolEnrollmentBand
from nevo.domain.billing.vocabulary import (
    InvoiceStatus,
    PaymentMethodType,
    SubscriptionTier,
)
from nevo.domain.permissions.vocabulary import PermissionScope
from nevo.intelligence.compliance_audit import render_simple_pdf
from nevo.permissions.entities import PermissionSnapshot

router = APIRouter(prefix="/api/billing", tags=["billing"])


class BillingContactResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    email: EmailStr
    phone: str | None
    address_line1: str = Field(alias="addressLine1")
    address_line2: str | None = Field(alias="addressLine2")
    city: str
    region: str | None
    postal_code: str | None = Field(alias="postalCode")
    country: str

    @classmethod
    def from_record(cls, record: BillingContactRecord) -> "BillingContactResponse":
        return cls(
            id=record.id,
            email=record.email,
            phone=record.phone,
            address_line1=record.address_line1,
            address_line2=record.address_line2,
            city=record.city,
            region=record.region,
            postal_code=record.postal_code,
            country=record.country,
        )


class PaymentMethodResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    method_type: PaymentMethodType = Field(alias="methodType")
    display_name: str = Field(alias="displayName")
    last_four: str = Field(alias="lastFour")
    card_brand: str | None = Field(alias="cardBrand")
    expiry_month: int | None = Field(alias="expiryMonth")
    expiry_year: int | None = Field(alias="expiryYear")
    bank_name: str | None = Field(alias="bankName")
    account_holder_name: str | None = Field(alias="accountHolderName")
    updated_at: datetime = Field(alias="updatedAt")

    @classmethod
    def from_record(cls, record: PaymentMethodRecord) -> "PaymentMethodResponse":
        return cls(
            id=record.id,
            method_type=record.method_type,
            display_name=record.display_name,
            last_four=record.last_four,
            card_brand=record.card_brand,
            expiry_month=record.expiry_month,
            expiry_year=record.expiry_year,
            bank_name=record.bank_name,
            account_holder_name=record.account_holder_name,
            updated_at=record.updated_at,
        )


class SubscriptionResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    school_id: UUID = Field(alias="schoolId")
    school_name: str = Field(alias="schoolName")
    subscription_tier: SubscriptionTier | None = Field(alias="subscriptionTier")
    student_count_band: SchoolEnrollmentBand | None = Field(alias="studentCountBand")
    contract_value: Decimal | None = Field(alias="contractValue")
    contract_start: datetime | None = Field(alias="contractStart")
    contract_end: datetime | None = Field(alias="contractEnd")
    renewal_banner_visible: bool = Field(alias="renewalBannerVisible")
    renewal_message: str | None = Field(alias="renewalMessage")
    billing_contact: BillingContactResponse | None = Field(alias="billingContact")
    payment_method: PaymentMethodResponse | None = Field(alias="paymentMethod")

    @classmethod
    def from_record(cls, record: SubscriptionRecord) -> "SubscriptionResponse":
        return cls(
            school_id=record.school_id,
            school_name=record.school_name,
            subscription_tier=record.subscription_tier,
            student_count_band=record.student_count_band,
            contract_value=record.contract_value,
            contract_start=record.contract_start,
            contract_end=record.contract_end,
            renewal_banner_visible=record.renewal_banner_visible,
            renewal_message=record.renewal_message,
            billing_contact=(
                BillingContactResponse.from_record(record.billing_contact)
                if record.billing_contact
                else None
            ),
            payment_method=(
                PaymentMethodResponse.from_record(record.payment_method)
                if record.payment_method
                else None
            ),
        )


class InvoiceResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    invoice_number: str = Field(alias="invoiceNumber")
    issued_at: date = Field(alias="issuedAt")
    amount: Decimal
    status: InvoiceStatus
    due_at: date = Field(alias="dueAt")
    paid_at: datetime | None = Field(alias="paidAt")
    pdf_url: str = Field(alias="pdfUrl")

    @classmethod
    def from_record(cls, record: InvoiceRecord) -> "InvoiceResponse":
        return cls(
            id=record.id,
            invoice_number=record.invoice_number,
            issued_at=record.issued_at,
            amount=record.amount,
            status=record.status,
            due_at=record.due_at,
            paid_at=record.paid_at,
            pdf_url=record.pdf_url,
        )


class UpcomingChargeResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    invoice_id: UUID | None = Field(alias="invoiceId")
    invoice_number: str | None = Field(alias="invoiceNumber")
    due_at: date | None = Field(alias="dueAt")
    amount: Decimal | None
    status: InvoiceStatus | None
    renewal_banner_visible: bool = Field(alias="renewalBannerVisible")
    renewal_message: str | None = Field(alias="renewalMessage")

    @classmethod
    def from_record(cls, record: UpcomingCharge) -> "UpcomingChargeResponse":
        return cls(
            invoice_id=record.invoice_id,
            invoice_number=record.invoice_number,
            due_at=record.due_at,
            amount=record.amount,
            status=record.status,
            renewal_banner_visible=record.renewal_banner_visible,
            renewal_message=record.renewal_message,
        )


class PaymentMethodRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    method_type: PaymentMethodType = Field(alias="methodType")
    display_name: str = Field(alias="displayName", min_length=2, max_length=120)
    last_four: str = Field(alias="lastFour", pattern=r"^\d{4}$")
    processor_name: str | None = Field(
        default=None,
        alias="processorName",
        max_length=80,
    )
    processor_payment_method_ref: str | None = Field(
        default=None,
        alias="processorPaymentMethodRef",
        max_length=255,
    )
    card_brand: str | None = Field(default=None, alias="cardBrand", max_length=80)
    expiry_month: int | None = Field(default=None, alias="expiryMonth", ge=1, le=12)
    expiry_year: int | None = Field(default=None, alias="expiryYear", ge=2026)
    bank_name: str | None = Field(default=None, alias="bankName", max_length=120)
    account_holder_name: str | None = Field(
        default=None,
        alias="accountHolderName",
        max_length=255,
    )


class BillingContactRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    email: EmailStr
    phone: str | None = Field(default=None, max_length=50)
    address_line1: str = Field(alias="addressLine1", min_length=1, max_length=255)
    address_line2: str | None = Field(default=None, alias="addressLine2", max_length=255)
    city: str = Field(min_length=1, max_length=120)
    region: str | None = Field(default=None, max_length=120)
    postal_code: str | None = Field(default=None, alias="postalCode", max_length=40)
    country: str = Field(min_length=2, max_length=120)

    @field_validator("phone")
    @classmethod
    def blank_phone_to_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


@router.get("/invoices/{school_id}/{invoice_number}.pdf")
async def invoice_pdf(
    school_id: UUID,
    invoice_number: str,
    actor: Annotated[
        PermissionSnapshot,
        Depends(RequireScope(PermissionScope.BILLING)),
    ],
    session: DatabaseSession,
) -> Response:
    if actor.school_id != school_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found")
    invoice = await session.scalar(
        select(Invoice).where(
            Invoice.school_id == school_id,
            Invoice.invoice_number == invoice_number,
        )
    )
    school = await session.get(School, school_id)
    if invoice is None or school is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found")
    content = render_simple_pdf(
        [
            "NEVO LEARNING INVOICE",
            f"Invoice: {invoice.invoice_number}",
            f"School: {school.name}",
            f"Issued: {invoice.issued_at.isoformat()}",
            f"Due: {invoice.due_at.isoformat()}",
            f"Amount: {invoice.amount}",
            f"Status: {invoice.status.value}",
            "This document was generated from the school's billing record.",
        ]
    )
    filename = f"{invoice.invoice_number}.pdf".replace('"', "")
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def get_billing_service(request: Request) -> BillingService:
    service = getattr(request.app.state, "billing_service", None)
    if not isinstance(service, BillingService):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "service_unavailable",
                "message": "Billing is temporarily unavailable.",
            },
        )
    return service


BillingDependency = Annotated[BillingService, Depends(get_billing_service)]
BillingScopeDependency = Annotated[
    PermissionSnapshot,
    Depends(RequireScope(PermissionScope.BILLING)),
]
DateFromQuery = Annotated[date | None, Query(alias="dateFrom")]
DateToQuery = Annotated[date | None, Query(alias="dateTo")]
InvoiceStatusQuery = Annotated[InvoiceStatus | None, Query(alias="status")]


@router.get("/subscription", response_model=SubscriptionResponse)
async def current_subscription(
    actor: BillingScopeDependency,
    service: BillingDependency,
) -> SubscriptionResponse:
    try:
        return SubscriptionResponse.from_record(await service.subscription(_school_id(actor)))
    except BillingError as error:
        raise public_billing_error(error) from error


@router.get("/invoices", response_model=list[InvoiceResponse])
async def invoice_history(
    actor: BillingScopeDependency,
    service: BillingDependency,
    date_from: DateFromQuery = None,
    date_to: DateToQuery = None,
    status_filter: InvoiceStatusQuery = None,
) -> list[InvoiceResponse]:
    try:
        records = await service.invoices(
            school_id=_school_id(actor),
            date_from=date_from,
            date_to=date_to,
            status=status_filter,
        )
    except BillingError as error:
        raise public_billing_error(error) from error
    return [InvoiceResponse.from_record(record) for record in records]


@router.get("/upcoming", response_model=UpcomingChargeResponse)
async def upcoming_charge(
    actor: BillingScopeDependency,
    service: BillingDependency,
) -> UpcomingChargeResponse:
    try:
        return UpcomingChargeResponse.from_record(await service.upcoming(_school_id(actor)))
    except BillingError as error:
        raise public_billing_error(error) from error


@router.put("/payment-method", response_model=PaymentMethodResponse)
async def update_payment_method(
    payload: PaymentMethodRequest,
    actor: BillingScopeDependency,
    service: BillingDependency,
) -> PaymentMethodResponse:
    try:
        record = await service.update_payment_method(
            school_id=_school_id(actor),
            actor_user_id=actor.user_id,
            update_data=PaymentMethodUpdate(
                method_type=payload.method_type,
                display_name=payload.display_name,
                last_four=payload.last_four,
                processor_name=payload.processor_name,
                processor_payment_method_ref=payload.processor_payment_method_ref,
                card_brand=payload.card_brand,
                expiry_month=payload.expiry_month,
                expiry_year=payload.expiry_year,
                bank_name=payload.bank_name,
                account_holder_name=payload.account_holder_name,
            ),
        )
    except BillingError as error:
        raise public_billing_error(error) from error
    return PaymentMethodResponse.from_record(record)


@router.put("/billing-contact", response_model=BillingContactResponse)
async def update_billing_contact(
    payload: BillingContactRequest,
    actor: BillingScopeDependency,
    service: BillingDependency,
) -> BillingContactResponse:
    try:
        record = await service.update_billing_contact(
            school_id=_school_id(actor),
            actor_user_id=actor.user_id,
            update_data=BillingContactUpdate(
                email=str(payload.email),
                phone=payload.phone,
                address_line1=payload.address_line1,
                address_line2=payload.address_line2,
                city=payload.city,
                region=payload.region,
                postal_code=payload.postal_code,
                country=payload.country,
            ),
        )
    except BillingError as error:
        raise public_billing_error(error) from error
    return BillingContactResponse.from_record(record)


def _school_id(actor: PermissionSnapshot) -> UUID:
    if actor.school_id is None:
        raise public_billing_error(BillingSchoolContextError())
    return actor.school_id


def public_billing_error(error: BillingError) -> HTTPException:
    status_code = status.HTTP_400_BAD_REQUEST
    if isinstance(error, BillingNotFoundError):
        status_code = status.HTTP_404_NOT_FOUND
    if isinstance(error, BillingSchoolContextError):
        status_code = status.HTTP_403_FORBIDDEN
    if isinstance(error, BillingPaymentMethodError):
        status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    return HTTPException(
        status_code=status_code,
        detail={
            "code": error.code,
            "message": error.public_message,
        },
    )
