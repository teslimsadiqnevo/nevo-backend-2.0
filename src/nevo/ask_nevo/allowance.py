"""How much Ask Nevo a person gets in a day, and what happens when it runs out.

The cap was written as "ten conversations per day", which bounds nothing. A
conversation is one short question or twenty long turns, and the cost of the
two differs by two orders of magnitude. Ask Nevo is the only part of the
product that calls a model while a child is using it, so the one number that
has to hold is money, not conversations.

So the allowance is measured in what is actually spent. A child gets a day's
worth, and when it is gone they are told plainly that they can come back
tomorrow - not that something went wrong, and not a silently worse answer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from nevo.domain.ask_nevo.vocabulary import AskNevoRole

#: Nigerian school days, so the allowance turns over at midnight in Lagos.
#: A day that resets at midnight UTC ends at one in the morning locally,
#: which is nobody's idea of a new day.
SCHOOL_TIMEZONE = ZoneInfo("Africa/Lagos")

#: Output tokens cost five times what input tokens cost, so a unit is one
#: input token's worth and output is charged at five. That keeps the
#: allowance proportional to the bill rather than to a token count, which
#: would let a long answer cost five times as much as the budget thought.
OUTPUT_WEIGHT = 5

#: A child's day. Derived rather than picked: about $4 of a child's annual
#: budget, over roughly 195 school days, at the rates this account pays -
#: which comes to six or seven typical questions a day.
STUDENT_DAILY_UNITS = 20_000

#: A teacher's day. Teacher questions carry more context and cost more, a
#: teacher planning a week will ask more than a child, and teacher seats are
#: free - so this is school-level spend rather than a child's. Three times a
#: child's, deliberately not unlimited: unbounded is the thing this exists
#: to prevent.
TEACHER_DAILY_UNITS = 60_000

#: What one exchange might cost, held back so an answer is never started that
#: the budget cannot finish. Being cut off mid-sentence reads as a fault; being
#: told the day is done reads as a rule.
RESERVE_UNITS = 4_000

DAILY_UNITS: dict[AskNevoRole, int] = {
    AskNevoRole.STUDENT: STUDENT_DAILY_UNITS,
    # A parent asks about their own child a few times a term, not daily, so a
    # child's allowance is more than enough and keeps one rule for families.
    AskNevoRole.PARENT: STUDENT_DAILY_UNITS,
    AskNevoRole.TEACHER: TEACHER_DAILY_UNITS,
    # An admin asks the same kind of question a teacher does, reaching
    # further, so they get the same day.
    AskNevoRole.ADMIN: TEACHER_DAILY_UNITS,
}


def units_for(*, input_tokens: int, output_tokens: int) -> int:
    """What one call costs against the allowance."""

    return max(0, input_tokens) + max(0, output_tokens) * OUTPUT_WEIGHT


def school_day(now: datetime) -> date:
    """The day this moment belongs to, where the child is."""

    return now.astimezone(SCHOOL_TIMEZONE).date()


def next_reset(now: datetime) -> datetime:
    """When the allowance comes back, so the refusal can say so."""

    tomorrow = school_day(now) + timedelta(days=1)
    return datetime.combine(tomorrow, time.min, tzinfo=SCHOOL_TIMEZONE)


@dataclass(frozen=True, slots=True)
class Allowance:
    """What is left of someone's day."""

    role: AskNevoRole
    day: date
    spent_units: int
    exchanges: int
    resets_at: datetime

    @property
    def daily_units(self) -> int:
        return DAILY_UNITS.get(self.role, STUDENT_DAILY_UNITS)

    @property
    def remaining_units(self) -> int:
        return max(0, self.daily_units - self.spent_units)

    @property
    def exhausted(self) -> bool:
        """True when there is not enough left to answer properly.

        Measured against the reserve rather than against zero: an answer that
        stops halfway is worse than one that was never started.
        """

        return self.remaining_units < RESERVE_UNITS

    @property
    def questions_left(self) -> int:
        """Roughly how many more questions, for a screen that shows it.

        Approximate on purpose. A person should be told "about three more
        today", not a number of tokens, which means nothing to a child and
        very little to a teacher.
        """

        return max(0, self.remaining_units // RESERVE_UNITS)

    def message(self) -> str:
        """What the person is told when the day is done.

        Not an error. They have used something up, the same way a library
        book comes back - so it says when, and it does not suggest they did
        anything wrong.
        """

        when = self.resets_at.astimezone(SCHOOL_TIMEZONE).strftime("%A morning")
        if self.role is AskNevoRole.TEACHER:
            return (
                "You have used today's Ask Nevo. It starts again on "
                f"{when}. Your lessons, classes and reports are all still here."
            )
        return (
            "That is all the questions Nevo can answer for you today. "
            f"Come back on {when} and ask again - your lessons are still here "
            "in the meantime."
        )
