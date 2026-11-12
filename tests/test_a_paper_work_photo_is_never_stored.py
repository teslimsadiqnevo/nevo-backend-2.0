"""A paper-work photo is never stored. ADR 0009, signed off 12 November.

Written before the camera route exists, on purpose. Lydia's concern is that the
rule erodes quietly, and a guard that is already here is one the first change
to break it runs into - rather than a reviewer noticing later, or nobody
noticing.

A photograph of an exercise book taken in a classroom catches faces, hands,
other children's work and the school's name, every day, with nobody intending
it. The step marks are the record and they are what everything downstream
reads, so keeping the image buys nothing.

If you are here because this test failed while you were adding the camera
route: read the ADR. The rule is that the image is held for the read and gone -
not written to disk, not in the media bucket, not in a backup, not kept when
the read fails, no thumbnail, no cache.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

MODULE = pathlib.Path(__file__).resolve().parents[1] / "src" / "nevo" / "api" / "paper_work.py"
ADR = (
    pathlib.Path(__file__).resolve().parents[1]
    / "docs"
    / "adr"
    / "0009-paper-work-photos-are-never-stored.md"
)

#: Names that mean the image came to rest somewhere.
#:
#: Deliberately broad. A photo reaching any of these is the thing the rule
#: forbids, and a guard that only knew about today's storage helper would
#: pass the day somebody used a different one.
PERSISTENCE = (
    "storage",
    "upload",
    "bucket",
    "media_service",
    "lesson_media",
    "open(",
    "write_bytes",
    "write_text",
    "NamedTemporaryFile",
    "mkstemp",
    "tempfile",
    "aiofiles",
    "Path(",
    "boto3",
    "put_object",
)

#: Names that mean the route takes an image at all.
IMAGE_INTAKE = ("UploadFile", "File(", "image", "photo", "bytes", "multipart")


def _source() -> str:
    return MODULE.read_text()


def _prose() -> str:
    """The ADR as one line, because markdown wraps and the rule does not.

    Blockquote markers come out too: Lydia's wording is quoted, and a "> " in
    the middle of a wrapped line would otherwise break a match on it.
    """
    lines = [line.lstrip("> ").rstrip() for line in ADR.read_text().splitlines()]
    return " ".join(" ".join(lines).split())


def test_the_module_takes_no_image_yet() -> None:
    """The current state: typed only, which is why nothing stores anything.

    When the camera route lands this test is expected to change - and the one
    below it is the one that must not.
    """
    source = _source()
    assert "typed_no_camera" in source
    assert "UploadFile" not in source


def test_nothing_in_the_paper_work_route_can_persist_anything() -> None:
    """The rule itself. This one holds whether or not a camera route exists."""
    source = _source()
    offenders = [name for name in PERSISTENCE if name in source]
    assert not offenders, (
        f"paper_work.py now mentions {offenders}. A paper-work photo is never "
        "written to disk, never put in the media bucket and never reaches a "
        "backup - see docs/adr/0009. If this is unrelated to images, the "
        "guard needs narrowing rather than deleting."
    )


def test_it_imports_nothing_that_could_store_an_image() -> None:
    tree = ast.parse(_source())
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)

    forbidden = [
        name
        for name in imported
        if any(part in name for part in ("storage", "media", "tempfile", "aiofiles", "pathlib"))
    ]
    assert not forbidden, f"paper_work.py imports {forbidden}; see docs/adr/0009"


def test_the_step_marks_are_the_record() -> None:
    """Which is why discarding the image costs nothing."""
    source = _source()
    assert "PaperWorkEvidence" in source or "paper_work_evidence" in source
    assert "counts_as_check_pass" in source


def test_the_decision_is_written_down_and_says_what_it_means() -> None:
    """A rule nobody can read is one that erodes."""
    adr = _prose()
    for clause in (
        "never written to disk",
        "never put in the media bucket",
        "never reaches a backup",
        "not kept on a failure",
        "No thumbnail",
    ):
        assert clause.casefold() in adr.casefold(), clause


def test_the_adr_keeps_the_two_things_built_with_the_route() -> None:
    """Both are Lydia's, and both are easy to drop under time pressure."""
    adr = _prose()
    # A refusal always leaves a way forward.
    assert "falls back to the typed route" in adr
    # And her exact wording, which must not be paraphrased.
    assert (
        "There is someone in this photo, so Nevo has not read it. Take another "
        "one of just your working." in adr
    )


@pytest.mark.parametrize(
    "loophole",
    [
        "keep the unreadable ones to debug with",
        "a thumbnail is not really the photo",
        "a cache is not storage",
    ],
)
def test_the_named_loopholes_stay_named(loophole: str) -> None:
    """Not a code check - a note to the next person, kept where they will look.

    Each of these is an argument that will be made in good faith. The ADR
    answers all three, and this test exists so that answering them is not
    rediscovered from scratch.
    """
    adr = _prose().casefold()
    assert "loophole" in adr
    assert "thumbnail" in adr
    assert "cache" in adr
    assert loophole  # the parameter is documentation; the assertions are the test
