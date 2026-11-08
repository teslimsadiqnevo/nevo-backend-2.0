"""An incident reference with nothing behind it helps nobody.

Food Chains.pdf failed four times on 8 November at the receiving_file
stage. Each attempt stored a reference, a generic sentence, and an empty
error_message - so neither the console nor I could say what went wrong.

Across every failed upload: 14 of 14 at finding_sections carried detail, 7
of 7 at preparing_adaptations did, and 0 of 9 at receiving_file did. Not a
coincidence of stage - the worker stored str(error), and an exception
raised without arguments has an empty str(). failure_reason already
composes the class name with the message for matching; the stored detail
threw the class name away precisely when it was the only thing left.
"""

from __future__ import annotations

import inspect

from nevo.content_parsing import upload_worker
from nevo.content_parsing.failures import GENERIC_FAILURE, failure_reason


class Bare(Exception):
    """Raised with no arguments, as several in the parse path are."""


def test_the_class_name_is_stored_even_with_no_message() -> None:
    source = inspect.getsource(upload_worker)
    assert 'f"{type(error).__name__}: {error}"' in source
    assert "job.error_message = str(error)" not in source


def test_a_bare_exception_leaves_something_behind() -> None:
    error = Bare()
    assert str(error) == ""
    stored = f"{type(error).__name__}: {error}".strip()
    assert stored == "Bare:"
    assert stored


def test_the_message_is_kept_when_there_is_one() -> None:
    error = Bare("the picture was refused")
    stored = f"{type(error).__name__}: {error}".strip()
    assert "Bare" in stored
    assert "the picture was refused" in stored


def test_classification_already_used_the_class_name() -> None:
    # Which is why the generic sentence was right and the empty detail was
    # not: the two disagreed about what they had to work with.
    assert failure_reason(Bare()) == GENERIC_FAILURE
    source = inspect.getsource(failure_reason)
    assert "error.__class__.__name__" in source


def test_detail_is_bounded() -> None:
    error = Bare("x" * 5000)
    assert len(f"{type(error).__name__}: {error}".strip()[:1000]) == 1000
