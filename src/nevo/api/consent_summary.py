from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from nevo.api.response_models import StudentConsentSummaryResponse
from nevo.db.models.account import ConsentRecord, User
from nevo.db.models.consent import ConsentInvitation, ConsentNotificationOutbox
from nevo.domain.accounts.vocabulary import ConsentStatus, ConsentType


async def student_consent_summaries(
    session: AsyncSession,
    student_ids: Iterable[UUID],
) -> dict[UUID, StudentConsentSummaryResponse]:
    ids = tuple(dict.fromkeys(student_ids))
    if not ids:
        return {}
    actor = aliased(User)
    record_rows = (
        await session.execute(
            select(ConsentRecord, actor)
            .outerjoin(actor, actor.id == ConsentRecord.last_actor_user_id)
            .where(
                ConsentRecord.subject_user_id.in_(ids),
                ConsentRecord.consent_type == ConsentType.DATA_PROCESSING,
            )
        )
    ).all()
    invitations = (
        await session.execute(
            select(ConsentInvitation, ConsentNotificationOutbox, actor)
            .join(
                ConsentNotificationOutbox,
                ConsentNotificationOutbox.invitation_id == ConsentInvitation.id,
            )
            .outerjoin(actor, actor.id == ConsentInvitation.requested_by_user_id)
            .where(ConsentInvitation.student_id.in_(ids))
            .order_by(ConsentInvitation.created_at.desc())
        )
    ).all()
    latest_invitation: dict[
        UUID,
        tuple[ConsentInvitation, ConsentNotificationOutbox, User | None],
    ] = {}
    for invitation, outbox, requested_by in invitations:
        latest_invitation.setdefault(
            invitation.student_id,
            (invitation, outbox, requested_by),
        )

    result: dict[UUID, StudentConsentSummaryResponse] = {}
    for record, changed_by in record_rows:
        if (
            record.status is ConsentStatus.PENDING
            and record.subject_user_id not in latest_invitation
        ):
            continue
        actor_id = record.last_actor_user_id
        actor_name = _name(changed_by) if changed_by is not None else None
        result[record.subject_user_id] = StudentConsentSummaryResponse(
            status=record.status,
            actor_id=actor_id,
            actor_name=actor_name,
            timestamp=record.last_changed_at or record.confirmed_at,
            channel=record.last_channel
            or (record.confirmed_via.value if record.confirmed_via is not None else None),
        )
    for student_id, (invitation, outbox, requested_by) in latest_invitation.items():
        if student_id in result and result[student_id].status is not ConsentStatus.PENDING:
            continue
        result[student_id] = StudentConsentSummaryResponse(
            status=ConsentStatus.PENDING,
            actor_id=invitation.requested_by_user_id,
            actor_name=_name(requested_by) if requested_by is not None else None,
            timestamp=outbox.sent_at or invitation.created_at,
            channel=outbox.contact_method.value,
        )
    return result


def empty_consent_summary() -> StudentConsentSummaryResponse:
    return StudentConsentSummaryResponse(status=ConsentStatus.NOT_SENT)


def _name(user: User) -> str:
    return " ".join(part for part in (user.first_name, user.last_name) if part) or "School admin"
