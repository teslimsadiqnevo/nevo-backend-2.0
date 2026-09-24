"""What a teacher is told when a lesson could not be prepared.

Two doors into the same pipeline both recorded a failure, and both recorded
only what the driver or the provider said. On the staged route that went out
as ``error``; on the content route it went out as ``failureReason``, a name
that promises prose and delivered a stack trace's first line. A console
rendered one of them to teachers verbatim, which is how a school owner came
to read a Postgres error.

So the raw text stays, named for what it is and kept for us to report with,
and the sentence a teacher reads is worked out here. Both doors use this one,
because a lesson failing the same way on two routes should not say two
different things.
"""

from __future__ import annotations

from uuid import uuid4

#: When we cannot say anything specific. Deliberately not a paraphrase of the
#: exception: a guess dressed as a diagnosis sends a teacher to fix the wrong
#: thing, and saying plainly that we do not know is more use than that.
GENERIC_FAILURE = (
    "Nevo could not finish preparing this lesson. Nothing you did caused it. "
    "Try uploading it again, and tell us the reference below if it happens twice."
)

#: A small closed list, and it stays small. Every entry earns its place by
#: naming something a teacher can actually do next.
FAILURE_REASONS: tuple[tuple[tuple[str, ...], str], ...] = (
    (
        ("no readable", "no text", "empty", "no lesson text"),
        "We could not find any lesson text in that file. If it is a scan, a "
        "version with selectable text will work better.",
    ),
    (
        ("timeout", "timed out", "readtimeout"),
        "Preparing this lesson took longer than we allow. It is usually a very "
        "long document - splitting it into separate lessons will get through.",
    ),
    (
        ("rate limit", "429", "too many requests"),
        "Nevo is busy preparing other lessons right now. Try this one again in a few minutes.",
    ),
    (
        ("does not exist", "undefinedcolumn", "undefinedtable", "relation"),
        "Nevo could not save this lesson. This is a fault at our end and not "
        "anything about your file - we have been told, and the reference below "
        "finds it.",
    ),
)


def failure_reason(error: BaseException | str) -> str:
    """A sentence a teacher can act on, or an honest generic one."""

    text = (
        f"{error.__class__.__name__} {error}" if isinstance(error, BaseException) else str(error)
    ).casefold()
    for markers, sentence in FAILURE_REASONS:
        if any(marker in text for marker in markers):
            return sentence
    return GENERIC_FAILURE


def new_incident() -> str:
    """The reference a failure is quoted by.

    The same twelve hex characters an unhandled 500 carries, so a teacher
    quoting one does not have to know which kind of failure they met.
    """

    return uuid4().hex[:12]
