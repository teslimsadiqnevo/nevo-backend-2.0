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

import re
from enum import StrEnum
from uuid import uuid4


class UploadReasonCode(StrEnum):
    FILE_TOO_LARGE = "file_too_large"
    UNSUPPORTED_FILE_TYPE = "unsupported_file_type"
    UNREADABLE_FILE = "unreadable_file"
    NO_READABLE_TEXT = "no_readable_text"
    PREPARATION_TIMEOUT = "preparation_timeout"
    SERVICE_BUSY = "service_busy"
    SAVE_FAILED = "save_failed"
    OUTPUT_LIMIT = "output_limit"
    PARTIAL_READING = "partial_reading"
    UNCLASSIFIABLE_QUESTION = "unclassifiable_question"
    UNKNOWN = "unknown"


def _matches(text: str, marker: str) -> bool:
    if marker.isdecimal():
        return re.search(r"\b" + re.escape(marker) + r"\b", text) is not None
    return marker in text


def failure_code(error: BaseException | str) -> UploadReasonCode:
    text = (
        f"{error.__class__.__name__} {error}" if isinstance(error, BaseException) else str(error)
    ).casefold()
    rules = (
        (
            UploadReasonCode.UNCLASSIFIABLE_QUESTION,
            (
                "unclassifiablequestionerror",
                "unclassifiable question",
                "unmarkable choice question",
                "unsupported question type",
                "question correction",
            ),
        ),
        (UploadReasonCode.FILE_TOO_LARGE, ("exceeds 50 mb", "file_too_large")),
        (UploadReasonCode.UNSUPPORTED_FILE_TYPE, ("upload a txt", "unsupported file")),
        (
            UploadReasonCode.UNREADABLE_FILE,
            ("could not read", "badzipfile", "not a zip", "invalid pdf"),
        ),
        (UploadReasonCode.NO_READABLE_TEXT, ("no readable", "no text", "empty", "no lesson text")),
        (UploadReasonCode.PREPARATION_TIMEOUT, ("timeout", "timed out", "readtimeout")),
        (UploadReasonCode.SERVICE_BUSY, ("rate limit", "429", "too many requests")),
        (
            UploadReasonCode.SAVE_FAILED,
            ("does not exist", "undefinedcolumn", "undefinedtable", "relation", "value too long"),
        ),
        (UploadReasonCode.OUTPUT_LIMIT, ("max_tokens", "token limit", "truncated")),
    )
    for code, markers in rules:
        if any(_matches(text, marker) for marker in markers):
            return code
    return UploadReasonCode.UNKNOWN


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
        (
            "unclassifiablequestionerror",
            "unclassifiable question",
            "unmarkable choice question",
            "unsupported question type",
            "question correction",
        ),
        "A question could not be prepared with a usable answer. The lesson has not been "
        "published. Please retry preparation and share the reference if it happens again.",
    ),
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
        ("does not exist", "undefinedcolumn", "undefinedtable", "relation", "value too long"),
        "Nevo could not save this lesson. This is a fault at our end and not "
        "anything about your file - we have been told, and the reference below "
        "finds it.",
    ),
)


def failure_reason(error: BaseException | str) -> str:
    """A sentence a teacher can act on, or an honest generic one."""

    label = getattr(error, "question_label", None)
    if not label:
        match = re.search(r'Question: "([^"\n]{1,160})"', str(error))
        label = match.group(1) if match else None
    if label:
        return (
            f'The question "{label}" has no usable marking rule. '
            "The lesson has not been published. Please correct this question and upload again."
        )
    text = (
        f"{error.__class__.__name__} {error}" if isinstance(error, BaseException) else str(error)
    ).casefold()
    for markers, sentence in FAILURE_REASONS:
        if any(_matches(text, marker) for marker in markers):
            return sentence
    return GENERIC_FAILURE


def new_incident() -> str:
    """The reference a failure is quoted by.

    The same twelve hex characters an unhandled 500 carries, so a teacher
    quoting one does not have to know which kind of failure they met.
    """

    return uuid4().hex[:12]
