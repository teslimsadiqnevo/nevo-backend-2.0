from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nevo.consent.entities import (
    ConsentRecordView,
    ParentAccount,
    ParentChildView,
    ParentConsentCompletion,
    ParentConsentRequestDraft,
    ParentInvitationView,
    ParentLinkView,
    ParentRightOutcome,
    QueuedParentConsentRequest,
)
from nevo.consent.errors import (
    ParentAccountConflictError,
    ParentContactNotEmailError,
    StudentNotFoundError,
)
from nevo.db.models.account import ConsentRecord, School, User
from nevo.db.models.billing import BillingContact
from nevo.db.models.consent import (
    ConsentInvitation,
    ConsentInvitationItem,
    ConsentNotificationOutbox,
    ParentLink,
)
from nevo.db.models.product import ParentDataRequest
from nevo.domain.accounts.vocabulary import (
    AuthMethod,
    ConsentMethod,
    ConsentStatus,
    ConsentType,
    UserRole,
    UserStatus,
)
from nevo.domain.consent.vocabulary import (
    REQUIRED_LEARNING_CONSENT,
    ConsentConfirmationSource,
    ConsentDeliveryStatus,
    ConsentNotificationKind,
    ParentContactMethod,
    ParentRightType,
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
                    record.confirmation_source = ConsentConfirmationSource.SCHOOL
                    record.confirmed_by_admin_id = confirmed_by_user_id
                    record.confirmed_by_parent_id = None
                    record.confirmed_via = confirmed_via
                    record.confirmed_at = confirmed_at
                    record.last_actor_user_id = confirmed_by_user_id
                    record.last_changed_at = confirmed_at
                    record.last_channel = confirmed_via.value
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
                            ConsentInvitationItem.invitation_id == invitation.id
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
                        record.confirmation_source = ConsentConfirmationSource.PARENT
                        record.confirmed_by_admin_id = None
                        record.confirmed_by_parent_id = parent.id
                        record.confirmed_via = ConsentMethod.DIGITAL
                        record.confirmed_at = completed_at
                        record.last_actor_user_id = parent.id
                        record.last_changed_at = completed_at
                        record.last_channel = ConsentMethod.DIGITAL.value

                parent_link.parent_id = parent.id
                parent_link.account_created = True
                parent_link.updated_at = completed_at
                invitation.accepted_at = completed_at
                await session.execute(
                    update(ConsentNotificationOutbox)
                    .where(ConsentNotificationOutbox.invitation_id == invitation.id)
                    .values(consent_url="")
                )
                # The copy the consent page promises. Queued rather than sent
                # inline so a mail outage cannot fail a consent the parent has
                # already given.
                session.add(
                    ConsentNotificationOutbox(
                        invitation_id=invitation.id,
                        contact_method=parent_link.contact_method,
                        destination=parent_link.parent_contact,
                        consent_url="",
                        kind=ConsentNotificationKind.RECEIPT,
                    )
                )
                await session.flush()
                return ParentConsentCompletion(
                    invitation_id=invitation.id,
                    parent_link_id=parent_link.id,
                    parent_id=parent.id,
                    student_id=invitation.student_id,
                    confirmed_types=consent_types,
                    completed_at=completed_at,
                    receipt_sent_to=parent_link.contact_method,
                )
        except IntegrityError as error:
            raise ParentAccountConflictError from error

    async def activate_parent_account(
        self,
        *,
        token_digest: str,
        password_hash: str,
        now: datetime,
    ) -> ParentAccount | None:
        """Give the parent row that consent created a way to sign in.

        Consent already mints a parent user, linked to the child, in the
        invited state with no credential. Setting the password here is what
        turns it into an account, and the token is the authorisation: it was
        sent to that parent for that child.

        Idempotent in the sense that matters: an account that is already
        active is returned untouched rather than having its password reset by
        anyone holding an old link.
        """
        async with self._sessions.begin() as session:
            invitation = await session.scalar(
                select(ConsentInvitation).where(
                    ConsentInvitation.token_digest == token_digest,
                    ConsentInvitation.revoked_at.is_(None),
                )
            )
            if invitation is None or invitation.expires_at <= now:
                return None
            link = await session.get(ParentLink, invitation.parent_link_id)
            if link is None:
                return None
            if link.contact_method is not ParentContactMethod.EMAIL:
                raise ParentContactNotEmailError

            parent = await self._parent_for_link(session, parent_link=link)
            await session.flush()
            link.parent_id = parent.id
            link.account_created = True
            link.updated_at = now
            if parent.status is UserStatus.ACTIVE and parent.password_hash:
                return ParentAccount(
                    user_id=parent.id,
                    email=parent.email or link.parent_contact,
                    student_id=link.student_id,
                    already_active=True,
                )
            parent.email = parent.email or link.parent_contact.casefold()
            parent.auth_method = AuthMethod.EMAIL_PASSWORD
            parent.password_hash = password_hash
            parent.status = UserStatus.ACTIVE
            parent.deactivated_at = None
            await session.flush()
            return ParentAccount(
                user_id=parent.id,
                email=parent.email,
                student_id=link.student_id,
                already_active=False,
            )

    async def children_for_parent(self, parent_id: UUID) -> list[ParentChildView]:
        """The children this parent is linked to, and nobody else's.

        Every parent-facing read starts here: the link table is the only thing
        that says which learners are theirs.
        """
        async with self._sessions() as session:
            rows = (
                await session.execute(
                    select(
                        ParentLink.student_id,
                        User.first_name,
                        User.last_name,
                        User.status,
                        ParentLink.school_id,
                        School.name,
                    )
                    .join(User, User.id == ParentLink.student_id)
                    .join(School, School.id == ParentLink.school_id)
                    .where(ParentLink.parent_id == parent_id)
                    .order_by(User.first_name, User.last_name)
                )
            ).all()
        return [
            ParentChildView(
                student_id=student_id,
                first_name=first_name,
                last_name=last_name,
                status=status,
                school_id=school_id,
                school_name=school_name,
            )
            for student_id, first_name, last_name, status, school_id, school_name in rows
        ]

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

    async def consent_status(
        self,
        *,
        student_id: UUID,
        consent_type: ConsentType,
    ) -> ConsentStatus:
        """The stored status, so a withdrawal is not reported as pending.

        A learner who was never asked and a learner whose parent withdrew both
        fail the gate, but the screens they need are opposite: one is a
        reminder to the school, the other is a suspension notice.
        """
        async with self._sessions() as session:
            status = await session.scalar(
                select(ConsentRecord.status)
                .where(
                    ConsentRecord.subject_user_id == student_id,
                    ConsentRecord.consent_type == consent_type,
                )
                .limit(1)
            )
        return status or ConsentStatus.NOT_SENT

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

    async def parent_invitation(
        self,
        *,
        token_digest: str,
        now: datetime,
    ) -> ParentInvitationView | None:
        """Resolve a parent's token into the details their screen must name.

        Returns None for a link that is unknown, revoked, or expired. An
        accepted link still resolves: a parent who already decided needs to
        arrive at the state of that decision, not at the question again.
        """
        async with self._sessions() as session:
            invitation = await session.scalar(
                select(ConsentInvitation).where(
                    ConsentInvitation.token_digest == token_digest,
                    ConsentInvitation.revoked_at.is_(None),
                )
            )
            if invitation is None or invitation.expires_at <= now:
                return None

            row = (
                await session.execute(
                    select(
                        User.first_name,
                        School.name,
                        BillingContact.phone,
                        BillingContact.email,
                    )
                    .select_from(ConsentInvitation)
                    .join(User, User.id == ConsentInvitation.student_id)
                    .join(School, School.id == ConsentInvitation.school_id)
                    .outerjoin(
                        BillingContact,
                        BillingContact.school_id == ConsentInvitation.school_id,
                    )
                    .where(ConsentInvitation.id == invitation.id)
                )
            ).first()
            if row is None:
                return None
            student_first_name, school_name, school_phone, school_email = row

            parent_link = await session.get(ParentLink, invitation.parent_link_id)
            consent_types = frozenset(
                await session.scalars(
                    select(ConsentInvitationItem.consent_type).where(
                        ConsentInvitationItem.invitation_id == invitation.id
                    )
                )
            )
            record = (
                await session.execute(
                    select(ConsentRecord.status, ConsentRecord.last_changed_at)
                    .where(
                        ConsentRecord.subject_user_id == invitation.student_id,
                        ConsentRecord.consent_type == REQUIRED_LEARNING_CONSENT,
                    )
                )
            ).first()

        status = record[0] if record is not None else ConsentStatus.PENDING
        decided_at = record[1] if record is not None else None
        if invitation.accepted_at is not None and status is ConsentStatus.PENDING:
            # The link was used but the record was seeded for a different type.
            status = ConsentStatus.CONFIRMED
            decided_at = invitation.accepted_at
        return ParentInvitationView(
            invitation_id=invitation.id,
            student_id=invitation.student_id,
            student_first_name=student_first_name or "your child",
            school_name=school_name,
            school_phone=school_phone,
            school_email=school_email,
            parent_name=parent_link.parent_name if parent_link else "Parent or guardian",
            status=status,
            consent_types=consent_types,
            expires_at=invitation.expires_at,
            decided_at=decided_at if status is not ConsentStatus.PENDING else None,
        )

    async def exercise_parent_right(
        self,
        *,
        token_digest: str,
        request_type: ParentRightType,
        reason: str | None,
        now: datetime,
    ) -> ParentRightOutcome | None:
        """Record a right the parent exercised against their own child.

        The token is the authorisation: it was sent to that parent, for that
        child. Withdrawal both suspends the learner and moves the consent
        record, so the gate and the roster agree about what happened.
        """
        async with self._sessions.begin() as session:
            invitation = await session.scalar(
                select(ConsentInvitation).where(
                    ConsentInvitation.token_digest == token_digest,
                    ConsentInvitation.revoked_at.is_(None),
                )
            )
            if invitation is None or invitation.expires_at <= now:
                return None
            link = await session.get(ParentLink, invitation.parent_link_id)
            if link is None:
                return None
            parent_id = link.parent_id
            if parent_id is None:
                # A parent who never completed the link still holds rights over
                # their child's data, so create the account the link implies
                # rather than turning them away.
                parent = await self._parent_for_link(session, parent_link=link)
                await session.flush()
                link.parent_id = parent.id
                # ck_parent_links_account_created_matches_parent: the flag and
                # the id have to move together.
                link.account_created = True
                link.updated_at = now
                parent_id = parent.id

            request = ParentDataRequest(
                student_id=link.student_id,
                parent_id=parent_id,
                request_type=request_type.value,
                reason=reason,
            )
            session.add(request)

            if request_type is ParentRightType.WITHDRAW_CONSENT:
                student = await session.get(User, link.student_id)
                if student is not None:
                    student.status = UserStatus.DEACTIVATED
                    student.deactivated_at = now
                consent = await self._ensure_pending_record(
                    session,
                    student_id=link.student_id,
                    consent_type=REQUIRED_LEARNING_CONSENT,
                )
                if consent.status is not ConsentStatus.WITHDRAWN:
                    consent.status = ConsentStatus.WITHDRAWN
                    consent.last_actor_user_id = parent_id
                    consent.last_changed_at = now
                    consent.last_channel = "parent_portal"
            await session.flush()
            return ParentRightOutcome(
                request_id=request.id,
                request_type=request_type,
                status=request.status,
                reason_recorded=bool(reason),
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
                select(User).where(User.id == parent_link.parent_id).with_for_update()
            )
            if linked_parent is None:
                raise ParentAccountConflictError
            return linked_parent

        parent: User | None = None
        if parent_link.contact_method is ParentContactMethod.EMAIL:
            parent = await session.scalar(
                select(User)
                .where(func.lower(User.email) == parent_link.parent_contact.casefold())
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
                    if parent_link.contact_method is ParentContactMethod.EMAIL
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
