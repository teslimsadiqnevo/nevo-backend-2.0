from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nevo.consent.entities import (
    ConsentRecordView,
    ParentConsentCompletion,
    ParentConsentRequestDraft,
    ParentLinkView,
    QueuedParentConsentRequest,
)
from nevo.consent.errors import (
    ParentAccountConflictError,
    StudentNotFoundError,
)
from nevo.db.models.account import ConsentRecord, User
from nevo.db.models.consent import (
    ConsentInvitation,
    ConsentInvitationItem,
    ConsentNotificationOutbox,
    ParentLink,
)
from nevo.domain.accounts.vocabulary import (
    AuthMethod,
    ConsentMethod,
    ConsentStatus,
    ConsentType,
    UserRole,
    UserStatus,
)
from nevo.domain.consent.vocabulary import (
    ConsentConfirmationSource,
    ConsentDeliveryStatus,
    ParentContactMethod,
)


class SqlAlchemyConsentRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def confirm_by_school(
        self,
        *,
        school_id: UUID,
        student_id: UUID,
        consent_types: frozenset[ConsentType],
        confirmed_by_user_id: UUID,
        confirmed_via: ConsentMethod,
        confirmed_at: datetime,
    ) -> list[ConsentRecordView]:
        async with self._sessions.begin() as session:
            await self._require_student(
                session,
                school_id=school_id,
                student_id=student_id,
            )
            records: list[ConsentRecord] = []
            for consent_type in consent_types:
                record = await self._consent_for_update(
                    session,
                    student_id=student_id,
                    consent_type=consent_type,
                )
                if record is None:
                    record = ConsentRecord(
                        id=uuid4(),
                        subject_user_id=student_id,
                        consent_type=consent_type,
                    )
                    session.add(record)
                if record.status is ConsentStatus.PENDING:
                    record.status = ConsentStatus.CONFIRMED
                    record.confirmation_source = (
                        ConsentConfirmationSource.SCHOOL
                    )
                    record.confirmed_by_admin_id = confirmed_by_user_id
                    record.confirmed_by_parent_id = None
                    record.confirmed_via = confirmed_via
                    record.confirmed_at = confirmed_at
                records.append(record)
            await session.flush()
            return [self._consent_view(record) for record in records]

    async def create_parent_request(
        self,
        draft: ParentConsentRequestDraft,
    ) -> QueuedParentConsentRequest:
        try:
            async with self._sessions.begin() as session:
                await self._require_student(
                    session,
                    school_id=draft.school_id,
                    student_id=draft.student_id,
                )
                parent_link = await session.scalar(
                    select(ParentLink)
                    .where(
                        ParentLink.student_id == draft.student_id,
                        ParentLink.parent_contact == draft.parent_contact,
                        ParentLink.contact_method == draft.contact_method,
                    )
                    .with_for_update()
                )
                if parent_link is None:
                    parent_link = ParentLink(
                        id=draft.parent_link_id,
                        school_id=draft.school_id,
                        student_id=draft.student_id,
                        parent_name=draft.parent_name,
                        parent_contact=draft.parent_contact,
                        contact_method=draft.contact_method,
                    )
                    session.add(parent_link)
                else:
                    parent_link.parent_name = draft.parent_name

                # UUID-only references do not give the unit of work a Python
                # relationship to order against, so persist each FK parent
                # before constructing its children.
                await session.flush()
                await session.execute(
                    update(ConsentInvitation)
                    .where(
                        ConsentInvitation.parent_link_id == parent_link.id,
                        ConsentInvitation.accepted_at.is_(None),
                        ConsentInvitation.revoked_at.is_(None),
                    )
                    .values(revoked_at=draft.created_at)
                )
                invitation = ConsentInvitation(
                    id=draft.invitation_id,
                    parent_link_id=parent_link.id,
                    school_id=draft.school_id,
                    student_id=draft.student_id,
                    token_digest=draft.token_digest,
                    requested_by_user_id=draft.requested_by_user_id,
                    created_at=draft.created_at,
                    expires_at=draft.expires_at,
                )
                session.add(invitation)
                await session.flush()
                for consent_type in draft.consent_types:
                    session.add(
                        ConsentInvitationItem(
                            invitation_id=invitation.id,
                            consent_type=consent_type,
                        )
                    )
                    await self._ensure_pending_record(
                        session,
                        student_id=draft.student_id,
                        consent_type=consent_type,
                    )
                session.add(
                    ConsentNotificationOutbox(
                        invitation_id=invitation.id,
                        contact_method=draft.contact_method,
                        destination=draft.parent_contact,
                        consent_url=draft.consent_url,
                    )
                )
                await session.flush()
                return QueuedParentConsentRequest(
                    invitation_id=invitation.id,
                    parent_link_id=parent_link.id,
                    student_id=draft.student_id,
                    consent_types=draft.consent_types,
                    delivery_status=ConsentDeliveryStatus.QUEUED,
                    expires_at=draft.expires_at,
                )
        except IntegrityError as error:
            raise ParentAccountConflictError from error

    async def complete_parent_request(
        self,
        *,
        token_digest: str,
        completed_at: datetime,
    ) -> ParentConsentCompletion | None:
        try:
            async with self._sessions.begin() as session:
                invitation = await session.scalar(
                    select(ConsentInvitation)
                    .where(ConsentInvitation.token_digest == token_digest)
                    .with_for_update()
                )
                if (
                    invitation is None
                    or invitation.accepted_at is not None
                    or invitation.revoked_at is not None
                    or invitation.expires_at <= completed_at
                ):
                    return None

                parent_link = await session.scalar(
                    select(ParentLink)
                    .where(ParentLink.id == invitation.parent_link_id)
                    .with_for_update()
                )
                if parent_link is None:
                    return None
                parent = await self._parent_for_link(
                    session,
                    parent_link=parent_link,
                )
                await session.flush()
                consent_types = frozenset(
                    await session.scalars(
                        select(ConsentInvitationItem.consent_type).where(
                            ConsentInvitationItem.invitation_id
                            == invitation.id
                        )
                    )
                )
                for consent_type in consent_types:
                    record = await self._consent_for_update(
                        session,
                        student_id=invitation.student_id,
                        consent_type=consent_type,
                    )
                    if record is None:
                        record = ConsentRecord(
                            id=uuid4(),
                            subject_user_id=invitation.student_id,
                            consent_type=consent_type,
                        )
                        session.add(record)
                    if record.status is ConsentStatus.PENDING:
                        record.status = ConsentStatus.CONFIRMED
                        record.confirmation_source = (
                            ConsentConfirmationSource.PARENT
                        )
                        record.confirmed_by_admin_id = None
                        record.confirmed_by_parent_id = parent.id
                        record.confirmed_via = ConsentMethod.DIGITAL
                        record.confirmed_at = completed_at

                parent_link.parent_id = parent.id
                parent_link.account_created = True
                parent_link.updated_at = completed_at
                invitation.accepted_at = completed_at
                await session.execute(
                    update(ConsentNotificationOutbox)
                    .where(
                        ConsentNotificationOutbox.invitation_id
                        == invitation.id
                    )
                    .values(consent_url="")
                )
                await session.flush()
                return ParentConsentCompletion(
                    invitation_id=invitation.id,
                    parent_link_id=parent_link.id,
                    parent_id=parent.id,
                    student_id=invitation.student_id,
                    confirmed_types=consent_types,
                    completed_at=completed_at,
                )
        except IntegrityError as error:
            raise ParentAccountConflictError from error

    async def parent_links(
        self,
        *,
        school_id: UUID,
        student_id: UUID,
    ) -> list[ParentLinkView]:
        async with self._sessions() as session:
            await self._require_student(
                session,
                school_id=school_id,
                student_id=student_id,
                lock=False,
            )
            links = list(
                await session.scalars(
                    select(ParentLink)
                    .where(
                        ParentLink.school_id == school_id,
                        ParentLink.student_id == student_id,
                    )
                    .order_by(ParentLink.parent_name)
                )
            )
        return [self._parent_link_view(link) for link in links]

    async def has_confirmed_consent(
        self,
        *,
        student_id: UUID,
        consent_type: ConsentType,
    ) -> bool:
        async with self._sessions() as session:
            record_id = await session.scalar(
                select(ConsentRecord.id)
                .where(
                    ConsentRecord.subject_user_id == student_id,
                    ConsentRecord.consent_type == consent_type,
                    ConsentRecord.status == ConsentStatus.CONFIRMED,
                )
                .limit(1)
            )
        return record_id is not None

    async def ensure_pending(
        self,
        *,
        student_id: UUID,
        consent_types: frozenset[ConsentType],
    ) -> None:
        async with self._sessions.begin() as session:
            student = await session.scalar(
                select(User.id)
                .where(
                    User.id == student_id,
                    User.role == UserRole.STUDENT,
                )
                .with_for_update()
            )
            if student is None:
                raise StudentNotFoundError
            for consent_type in consent_types:
                await self._ensure_pending_record(
                    session,
                    student_id=student_id,
                    consent_type=consent_type,
                )

    @staticmethod
    async def _require_student(
        session: AsyncSession,
        *,
        school_id: UUID,
        student_id: UUID,
        lock: bool = True,
    ) -> None:
        statement = select(User.id).where(
            User.id == student_id,
            User.school_id == school_id,
            User.role == UserRole.STUDENT,
            User.status != UserStatus.DEACTIVATED,
        )
        if lock:
            statement = statement.with_for_update()
        if await session.scalar(statement) is None:
            raise StudentNotFoundError

    @staticmethod
    async def _consent_for_update(
        session: AsyncSession,
        *,
        student_id: UUID,
        consent_type: ConsentType,
    ) -> ConsentRecord | None:
        record: ConsentRecord | None = await session.scalar(
            select(ConsentRecord)
            .where(
                ConsentRecord.subject_user_id == student_id,
                ConsentRecord.consent_type == consent_type,
            )
            .with_for_update()
        )
        return record

    @classmethod
    async def _ensure_pending_record(
        cls,
        session: AsyncSession,
        *,
        student_id: UUID,
        consent_type: ConsentType,
    ) -> ConsentRecord:
        existing = await cls._consent_for_update(
            session,
            student_id=student_id,
            consent_type=consent_type,
        )
        if existing is not None:
            return existing
        record = ConsentRecord(
            id=uuid4(),
            subject_user_id=student_id,
            consent_type=consent_type,
        )
        session.add(record)
        return record

    @staticmethod
    async def _parent_for_link(
        session: AsyncSession,
        *,
        parent_link: ParentLink,
    ) -> User:
        if parent_link.parent_id is not None:
            linked_parent = await session.scalar(
                select(User)
                .where(User.id == parent_link.parent_id)
                .with_for_update()
            )
            if linked_parent is None:
                raise ParentAccountConflictError
            return linked_parent

        parent: User | None = None
        if parent_link.contact_method is ParentContactMethod.EMAIL:
            parent = await session.scalar(
                select(User)
                .where(
                    func.lower(User.email)
                    == parent_link.parent_contact.casefold()
                )
                .with_for_update()
                .limit(1)
            )
            if parent is not None and (
                parent.role is not UserRole.PARENT_GUARDIAN
                or parent.school_id != parent_link.school_id
            ):
                raise ParentAccountConflictError
        if parent is None:
            parent = User(
                id=uuid4(),
                school_id=parent_link.school_id,
                role=UserRole.PARENT_GUARDIAN,
                auth_method=AuthMethod.EMAIL_PASSWORD,
                first_name=parent_link.parent_name,
                email=(
                    parent_link.parent_contact
                    if parent_link.contact_method
                    is ParentContactMethod.EMAIL
                    else None
                ),
                status=UserStatus.INVITED,
            )
            session.add(parent)
        return parent

    @staticmethod
    def _consent_view(record: ConsentRecord) -> ConsentRecordView:
        return ConsentRecordView(
            id=record.id,
            student_id=record.subject_user_id,
            consent_type=record.consent_type,
            status=record.status,
            confirmation_source=record.confirmation_source,
            confirmed_via=record.confirmed_via,
            confirmed_at=record.confirmed_at,
        )

    @staticmethod
    def _parent_link_view(link: ParentLink) -> ParentLinkView:
        return ParentLinkView(
            id=link.id,
            school_id=link.school_id,
            student_id=link.student_id,
            parent_id=link.parent_id,
            parent_name=link.parent_name,
            parent_contact=link.parent_contact,
            contact_method=link.contact_method,
            account_created=link.account_created,
        )
