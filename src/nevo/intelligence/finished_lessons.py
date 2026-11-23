"""Whether Nevo judges a lesson finished, on its own evidence.

completion_status is the player's declaration: it sends "completed" and we
record it. Of 41 sittings marked completed, 22 have no recorded answer at
all, so the number a learner profile is built from is half noise. Lydia,
22 November: the number is the lessons where the check was taken and marked,
stored as our decision rather than the app's claim.

THE RULE IS A CHOICE AND IT IS NOT SETTLED. Measured on 22 November:

    18  the app says completed AND a check was marked
    27  a check was marked AND the sitting has ended
    31  a check was marked, full stop

18 is the number Lydia reasoned from, and it is the only one of the three
that still consults the app's declaration - so "our decision rather than the
app's claim" and "18" cannot both hold. Until she picks, this uses the rule
that produces her number, because a figure she has already reasoned from is
the safer default. Changing it is the one constant below, and
scripts/rejudge_finished_lessons.py re-judges every existing sitting under
whichever rule is chosen, clearing the ones that no longer qualify.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from nevo.db.models.product import LessonQuestionAttempt
from nevo.db.models.signal_event import LessonSession
from nevo.domain.signal_events.vocabulary import LessonCompletionStatus

#: Settled by Lydia, 22 November: 31, on marked evidence alone.
#:
#: She chose 27 - evidence plus the sitting having ended - and asked whether
#: "ended" was ours or the app's. It is the app's: of the four paths that set
#: ended_at, three are the app telling us (a progress save declaring
#: completed or exited, a "stop for day" action, and a signal batch in which
#: the client supplies the timestamp itself), and the fourth is a staleness
#: sweep that means abandoned rather than finished. So by her own principle
#: it came out too.
#:
#: What the number counts is lessons that gave us marked evidence. A learner
#: who answered six checks and abandoned at segment five produced six checks
#: of evidence, and whether they reached a final screen adds nothing to that.
#:
#: "app_and_check" gives 18, "ended_and_check" 27, "check_only" 31.
RULE = "check_only"


def _marked_check_exists(session_id: UUID):
    """A checkpoint or end-of-lesson answer that we were able to mark.

    The evidence is that the child answered something markable, not that they
    got it right: a wrong answer is still a lesson they did.
    """
    return exists(
        select(LessonQuestionAttempt.id).where(
            LessonQuestionAttempt.session_id == session_id,
            LessonQuestionAttempt.source.in_(("checkpoint", "assessment")),
            LessonQuestionAttempt.correct.is_not(None),
        )
    )


async def judge_finished(
    session: AsyncSession,
    sitting: LessonSession,
    *,
    now: datetime | None = None,
) -> bool:
    """Set or clear our judgement on one sitting. Returns whether it stands.

    Clears as well as sets, so a sitting that qualified and then stopped
    qualifying - a mark withdrawn by a teacher, say - stops being counted.
    A judgement that only ever accumulates is not a judgement.

    Never touches completion_status. That is a record of what the app said,
    and we do not get to edit what somebody else told us.
    """
    has_check = await session.scalar(select(_marked_check_exists(sitting.id)))
    if RULE == "app_and_check":
        stands = bool(
            has_check
            and sitting.completion_status is LessonCompletionStatus.COMPLETED
        )
    elif RULE == "ended_and_check":
        stands = bool(has_check and sitting.ended_at is not None)
    else:
        stands = bool(has_check)

    if stands and sitting.verified_complete_at is None:
        sitting.verified_complete_at = sitting.ended_at or (now or datetime.now(UTC))
    elif not stands and sitting.verified_complete_at is not None:
        sitting.verified_complete_at = None
    return stands
