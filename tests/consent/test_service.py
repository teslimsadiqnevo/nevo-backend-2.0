from datetime import UTC, datetime
from uuid import uuid4

import pytest

from nevo.auth.entities import AuthPrincipal
from nevo.consent.entities import ConsentActor
from nevo.consent.errors import (
    ConsentRequiredError,
    InvalidConsentMethodError,
    InvalidParentContactError,
    StudentConsentAccessError,
)
from nevo.consent.service import ConsentService
from nevo.domain.accounts.vocabulary import (
    ConsentMethod,
    ConsentStatus,
    ConsentType,
)
from nevo.domain.consent.vocabulary import (
    ConsentConfirmationSource,
    ParentContactMethod,
)

from .fakes import FixedConsentTokenService, MemoryConsentRepository

NOW = datetime(2026, 7, 4, 12, 0, tzinfo=UTC)


def service() -> tuple[ConsentService, MemoryConsentRepository]:
    repository = MemoryConsentRepository()
    return (
        ConsentService(
            repository=repository,
            token_service=FixedConsentTokenService(),
            public_base_url="https://app.nevo.test/",
            now=lambda: NOW,
        ),
        repository,
    )


async def test_school_confirmation_records_school_source() -> None:
    consent_service, _ = service()
    student_id = uuid4()

    records = await consent_service.confirm_by_school(
        ConsentActor(user_id=uuid4(), school_id=uuid4()),
        student_id=student_id,
        consent_types=frozenset({ConsentType.DATA_PROCESSING}),
        confirmed_via=ConsentMethod.WRITTEN,
    )

    assert records[0].student_id == student_id
    assert records[0].status is ConsentStatus.CONFIRMED
    assert (
        records[0].confirmation_source
        is ConsentConfirmationSource.SCHOOL
    )


async def test_school_confirmation_rejects_parent_digital_method() -> None:
    consent_service, _ = service()

    with pytest.raises(InvalidConsentMethodError):
        await consent_service.confirm_by_school(
            ConsentActor(user_id=uuid4(), school_id=uuid4()),
            student_id=uuid4(),
            consent_types=frozenset({ConsentType.DATA_PROCESSING}),
            confirmed_via=ConsentMethod.DIGITAL,
        )


async def test_parent_request_normalizes_email_and_queues_link() -> None:
    consent_service, repository = service()

    queued = await consent_service.request_parent_consent(
        ConsentActor(user_id=uuid4(), school_id=uuid4()),
        student_id=uuid4(),
        parent_name="  Ada   Parent  ",
        parent_contact=" ADA@EXAMPLE.COM ",
        contact_method=ParentContactMethod.EMAIL,
        consent_types=frozenset({ConsentType.DATA_PROCESSING}),
    )

    draft = repository.requests[FixedConsentTokenService.digest_value]
    assert draft.parent_name == "Ada Parent"
    assert draft.parent_contact == "ada@example.com"
    assert draft.consent_url == (
        "https://app.nevo.test/consent/parent?"
        f"token={FixedConsentTokenService.token}"
    )
    assert queued.invitation_id == draft.invitation_id


async def test_parent_request_normalizes_international_phone() -> None:
    consent_service, repository = service()

    await consent_service.request_parent_consent(
        ConsentActor(user_id=uuid4(), school_id=uuid4()),
        student_id=uuid4(),
        parent_name="Ada Parent",
        parent_contact="00 234 (801) 234-5678",
        contact_method=ParentContactMethod.SMS,
        consent_types=frozenset(),
    )

    draft = repository.requests[FixedConsentTokenService.digest_value]
    assert draft.parent_contact == "+2348012345678"
    assert draft.consent_types == {ConsentType.DATA_PROCESSING}


async def test_invalid_parent_contact_is_rejected() -> None:
    consent_service, _ = service()

    with pytest.raises(InvalidParentContactError):
        await consent_service.request_parent_consent(
            ConsentActor(user_id=uuid4(), school_id=uuid4()),
            student_id=uuid4(),
            parent_name="Ada Parent",
            parent_contact="not-an-email",
            contact_method=ParentContactMethod.EMAIL,
            consent_types=frozenset({ConsentType.DATA_PROCESSING}),
        )


async def test_parent_completion_is_one_time_and_opens_gate() -> None:
    consent_service, _ = service()
    student_id = uuid4()
    await consent_service.request_parent_consent(
        ConsentActor(user_id=uuid4(), school_id=uuid4()),
        student_id=student_id,
        parent_name="Ada Parent",
        parent_contact="ada@example.com",
        contact_method=ParentContactMethod.EMAIL,
        consent_types=frozenset({ConsentType.DATA_PROCESSING}),
    )

    completion = await consent_service.complete_parent_consent(
        token=FixedConsentTokenService.token,
    )
    repeated = await consent_service.complete_parent_consent(
        token=FixedConsentTokenService.token,
    )
    gate = await consent_service.student_gate(
        AuthPrincipal(
            user_id=student_id,
            role="student",
            session_id=uuid4(),
        )
    )

    assert completion is not None
    assert repeated is None
    assert gate.granted


async def test_learning_gate_blocks_pending_student() -> None:
    consent_service, _ = service()
    principal = AuthPrincipal(
        user_id=uuid4(),
        role="student",
        session_id=uuid4(),
    )

    with pytest.raises(ConsentRequiredError):
        await consent_service.require_student_consent(principal)


async def test_non_student_cannot_query_student_gate() -> None:
    consent_service, _ = service()

    with pytest.raises(StudentConsentAccessError):
        await consent_service.student_gate(
            AuthPrincipal(
                user_id=uuid4(),
                role="teacher",
                session_id=uuid4(),
            )
        )


async def test_roster_initialization_defaults_to_pending() -> None:
    consent_service, repository = service()
    student_id = uuid4()

    await consent_service.initialize_roster_student(student_id)

    record = repository.records[
        (student_id, ConsentType.DATA_PROCESSING)
    ]
    assert record.status is ConsentStatus.PENDING
