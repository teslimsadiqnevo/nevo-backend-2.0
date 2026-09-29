"""What a child has covered and mastered this week, by subject.

The parent portal home is built on comprehension and mastery. Those are a
different thing from the transformation metrics that were struck: they are per
child by construction, they record what the child can now do, and they were
never a comparison. Nothing here returns a Self-Regulation Index, a
Metacognitive Calibration, a Conceptual Flexibility, an Active Learning
Efficiency, an index of any kind, a percentile, a rating, or any figure about
another child. The shapes below are incapable of carrying one - there is no
field for it - which is a stronger guarantee than a rule nobody reads.

Movement is always against the child's own starting point: what they had at the
start of the window against what they have now. Never against a classmate, a
class average or a year group.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from uuid import UUID
from zoneinfo import ZoneInfo

#: A Nigerian school week, so a week turns over at midnight in Lagos. A week
#: that starts at midnight UTC starts at one in the morning locally, which is
#: nobody's Monday.
SCHOOL_TIMEZONE = ZoneInfo("Africa/Lagos")

#: Where a concept counts as learned.
#:
#: Not a grade and not shown as a number. The engine caps a concept seeded from
#: the baseline probe at 0.7, so a threshold has to sit above that or a child
#: would read as having mastered something they were only estimated at. 0.85 is
#: far enough above it to mean real practice happened.
MASTERED_AT = 0.85


class WindowState(StrEnum):
    """What kind of week this was, so an empty one reads correctly.

    An empty week means three different things and the front end draws three
    different screens. Deciding which is ours: it depends on the school's term
    dates, and working it out per surface means three places to get it wrong.
    """

    #: School was on. An empty week is a quiet week.
    IN_TERM = "in_term"
    #: A holiday or a half-term break. An empty week is expected.
    IN_BREAK = "in_break"
    #: The school has not set its term dates, so we cannot say which.
    TERMS_NOT_SET = "terms_not_set"


class SubjectState(StrEnum):
    """Where a subject stands for this child in this window."""

    #: Work happened.
    ACTIVE = "active"
    #: The class holds this subject and no lesson has reached the child yet.
    #: Returned rather than the subject being left out, so the front end can
    #: render the state instead of guessing at a gap.
    NOT_STARTED = "not_started"


@dataclass(frozen=True, slots=True)
class Window:
    """Monday to Sunday in Lagos, and what kind of week it was."""

    starts_on: date
    ends_on: date
    state: WindowState
    #: True when this is the week in progress rather than a finished one, so a
    #: screen can say "so far" rather than reporting a part week as a whole.
    in_progress: bool


@dataclass(frozen=True, slots=True)
class SubjectProgress:
    """One subject, for one child, in one window.

    Counts and names only. There is deliberately nowhere to put a score.
    """

    subject_id: UUID
    subject_name: str
    state: SubjectState
    #: Concepts the child worked on in the window.
    covered: tuple[str, ...]
    #: Concepts that reached mastery during the window - movement against where
    #: this child started it, and against nothing else.
    mastered_this_window: tuple[str, ...]
    #: Practised and not yet there. The honest middle, and the part a parent
    #: most wants: what is being worked on right now.
    still_working_on: tuple[str, ...]
    #: How many the child had already mastered when the window opened, so a
    #: screen can say "three more, on top of the eleven before" without doing
    #: arithmetic the backend can do once.
    mastered_before_window: int


@dataclass(frozen=True, slots=True)
class ChildSubjectProgress:
    """Everything the parent portal home renders for one child."""

    student_id: UUID
    window: Window
    subjects: tuple[SubjectProgress, ...]


def week_containing(moment: datetime) -> tuple[date, date]:
    """The Monday-to-Sunday week a moment falls in, where the child is."""

    local = moment.astimezone(SCHOOL_TIMEZONE).date()
    monday = local - timedelta(days=local.weekday())
    return monday, monday + timedelta(days=6)


def window_bounds(starts_on: date, ends_on: date) -> tuple[datetime, datetime]:
    """The instants a stored timestamp is compared against.

    Local midnight at both ends, converted to UTC. Comparing a UTC timestamp
    against a bare date puts an hour of Sunday night into the wrong week.
    """

    start = datetime.combine(starts_on, time.min, tzinfo=SCHOOL_TIMEZONE)
    end = datetime.combine(ends_on + timedelta(days=1), time.min, tzinfo=SCHOOL_TIMEZONE)
    return start.astimezone(UTC), end.astimezone(UTC)


def state_for(
    starts_on: date,
    *,
    term_starts: list[date],
    breaks: list[tuple[date, date]],
) -> WindowState:
    """Whether school was on in this week.

    Deliberately conservative about what the data can answer. Term start dates
    say when a term begins and nothing records when one ends, so the long gap
    between terms is not detectable here and reads as in_term. A configured
    half-term break is, and so is any week before the first term of the year.
    When term end dates arrive this gets stricter without the callers changing.
    """

    if not term_starts:
        return WindowState.TERMS_NOT_SET
    ends_on = starts_on + timedelta(days=6)
    for break_start, break_end in breaks:
        # Any overlap at all: a week half in a break is not a normal week.
        if break_start <= ends_on and starts_on <= break_end:
            return WindowState.IN_BREAK
    if ends_on < min(term_starts):
        return WindowState.IN_BREAK
    return WindowState.IN_TERM


def build_window(
    *,
    now: datetime,
    starts_on: date | None,
    term_starts: list[date],
    breaks: list[tuple[date, date]],
) -> Window:
    """The week being asked about, defaulting to the one in progress.

    The default is the current week up to now, not the last complete one: a
    parent opening this on Wednesday wants to know about Wednesday.
    """

    today_monday, today_sunday = week_containing(now)
    if starts_on is None:
        monday, sunday = today_monday, today_sunday
    else:
        monday = starts_on - timedelta(days=starts_on.weekday())
        sunday = monday + timedelta(days=6)
    return Window(
        starts_on=monday,
        ends_on=sunday,
        state=state_for(monday, term_starts=term_starts, breaks=breaks),
        in_progress=monday == today_monday,
    )
