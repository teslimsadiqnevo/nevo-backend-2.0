"""Delete linked learner data; never mistake clearing a name for erasure."""

import hashlib
from collections import defaultdict

from sqlalchemy import Text, delete, or_, select, text

from nevo.db.base import Base

# Explicit ownership, rather than guessing that every staff author owns a pupil.
OWNERS = {
    "student_id",
    "learner_id",
    "subject_user_id",
    "actor_user_id",
    "user_id",
    "sender_id",
    "recipient_id",
}
EXCLUDED = {"users", "learner_purge_receipts"}


async def delete_learner_records(session, student):
    from nevo.db.models.account import User
    from nevo.db.models.ask_nevo import AskNevoInteraction, AskNevoMessage, AskNevoThread
    from nevo.db.models.frontend_support import Message, MessageThread, Notification
    from nevo.db.models.product import FeedbackSubmission

    # The append-only event trigger permits only a due, receipted retention purge.
    await session.execute(
        text("SELECT set_config('nevo.retention_student', :student, true)"),
        {"student": str(student.id)},
    )

    targets = defaultdict(set)
    feedback_ref = hashlib.sha256(str(student.id).encode()).hexdigest()[:16]
    targets["feedback_submissions"].update(
        await session.scalars(
            select(FeedbackSubmission.id).where(FeedbackSubmission.account_ref == feedback_ref)
        )
    )
    composite = {}
    for table in Base.metadata.sorted_tables:
        if table.name in EXCLUDED:
            continue
        owned = [
            column == student.id
            for column in table.c
            if column.name in OWNERS
            and any(fk.target_fullname == "users.id" for fk in column.foreign_keys)
        ]
        if table.name == "ai_gateway_calls":
            owned.append(table.c.requester_user_id == student.id)
        if table.name == "message_threads":
            owned.append(table.c.created_by_id == student.id)
        if owned:
            if "id" in table.c:
                targets[table.name].update(
                    await session.scalars(select(table.c.id).where(or_(*owned)))
                )
            else:
                composite[table.name] = or_(*owned)

    # Staff conversations about a pupil are learner data too, not just the pupil's own chats.
    interaction_ids = list(
        await session.scalars(
            select(AskNevoInteraction.id).where(
                AskNevoInteraction.context_ids.cast(Text).contains(str(student.id))
            )
        )
    )
    targets["ask_nevo_interactions"].update(interaction_ids)
    if interaction_ids:
        targets["ask_nevo_threads"].update(
            await session.scalars(
                select(AskNevoMessage.thread_id).where(
                    AskNevoMessage.interaction_id.in_(interaction_ids)
                )
            )
        )
    # Legacy transcripts/notifications may name a pupil without a structured context ID.
    names = [student.email, student.admission_number, student.login_identifier]
    if student.first_name not in {None, "Former"}:
        names.append(" ".join(part for part in (student.first_name, student.last_name) if part))
    names = [value for value in names if value and len(value) >= 3]
    if names and student.school_id:
        chat_filters = [AskNevoMessage.body.contains(value, autoescape=True) for value in names]
        targets["ask_nevo_threads"].update(
            await session.scalars(
                select(AskNevoThread.id)
                .join(AskNevoMessage, AskNevoMessage.thread_id == AskNevoThread.id)
                .where(AskNevoThread.school_id == student.school_id, or_(*chat_filters))
            )
        )
        note_filters = [
            Notification.description.contains(value, autoescape=True) for value in names
        ]
        note_filters.append(Notification.navigates_to.contains(str(student.id)))
        targets["notifications"].update(
            await session.scalars(
                select(Notification.id).where(
                    Notification.recipient_id.in_(
                        select(User.id).where(User.school_id == student.school_id)
                    ),
                    or_(*note_filters),
                )
            )
        )

        # A staff reply or class-thread preview can also contain the learner's name.
        message_filters = [Message.content.contains(value, autoescape=True) for value in names]
        targets["messages"].update(
            await session.scalars(
                select(Message.id)
                .join(MessageThread, Message.thread_id == MessageThread.id)
                .where(MessageThread.school_id == student.school_id, or_(*message_filters))
            )
        )

    affected_threads = (
        set(
            await session.scalars(
                select(Message.thread_id).where(Message.id.in_(targets["messages"]))
            )
        )
        if targets["messages"]
        else set()
    )

    # Expand only from owned records to dependent records, never to shared parents.
    changed = True
    while changed:
        changed = False
        for table in Base.metadata.sorted_tables:
            if table.name in EXCLUDED or "id" not in table.c:
                continue
            predicates = [
                column.in_(targets[fk.column.table.name])
                for column in table.c
                for fk in column.foreign_keys
                if fk.column.name == "id"
                and fk.column.table.name != "users"
                and targets[fk.column.table.name]
            ]
            if predicates:
                found = set(await session.scalars(select(table.c.id).where(or_(*predicates))))
                if found - targets[table.name]:
                    targets[table.name].update(found)
                    changed = True
    counts = {}
    for table in reversed(Base.metadata.sorted_tables):
        ids = targets[table.name]
        if ids and table.name not in EXCLUDED:
            await session.execute(delete(table).where(table.c.id.in_(ids)))
            counts[table.name] = len(ids)
        elif table.name in composite:
            result = await session.execute(delete(table).where(composite[table.name]))
            counts[table.name] = result.rowcount
    for thread_id in affected_threads - targets["message_threads"]:
        thread = await session.get(MessageThread, thread_id)
        if thread is not None:
            # Do not leave a copied snippet of a deleted message behind.
            thread.latest_preview = None
    return counts


def clear_identity(student, now):
    from nevo.retention.anonymisation import anonymise_student

    anonymise_student(student, now=now)
    for field in (
        "admission_number",
        "preferred_name",
        "date_of_birth",
        "age_band",
        "avatar_tone",
        "pin_cleared_at",
        "email_confirmed_at",
        "school_id",
    ):
        setattr(student, field, None)
    student.retention_purged_at = now
