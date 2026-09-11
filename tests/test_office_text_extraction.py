"""Reading a Word or PowerPoint upload.

Most lessons arrive as .docx. What the parse can do with one depends entirely
on whether the document still has lines in it when it reaches the model: a
heading has to look like a heading, and one working step has to end before the
next begins.
"""

from __future__ import annotations

import io
import zipfile

import pytest
from fastapi import HTTPException

from nevo.api.frontend_unblockers import _extract_office_text

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"


def _docx(*paragraphs: str) -> bytes:
    body = "".join(
        f'<w:p><w:r><w:t xml:space="preserve">{text}</w:t></w:r></w:p>' for text in paragraphs
    )
    return _package(
        {
            "word/document.xml": f'<w:document xmlns:w="{W}"><w:body>{body}</w:body></w:document>',
            # Noise Word puts in every package. None of it is lesson text.
            "word/styles.xml": f'<w:styles xmlns:w="{W}"><w:docDefaults/></w:styles>',
            "word/fontTable.xml": f'<w:fonts xmlns:w="{W}"><w:font w:name="Calibri"/></w:fonts>',
        }
    )


def _package(parts: dict[str, str]) -> bytes:
    raw = io.BytesIO()
    with zipfile.ZipFile(raw, "w") as archive:
        for name, content in parts.items():
            archive.writestr(name, content)
    return raw.getvalue()


def test_paragraphs_come_back_as_lines() -> None:
    text = _extract_office_text(
        _docx("Worked example one", "Step 1. Write down what you know.", "P = 20000, R = 5")
    )
    assert text.splitlines() == [
        "Worked example one",
        "Step 1. Write down what you know.",
        "P = 20000, R = 5",
    ]


def test_a_soft_break_is_a_line_too() -> None:
    body = (
        "<w:p><w:r><w:t>first</w:t><w:br/><w:t>second</w:t></w:r></w:p>"
        "<w:p><w:r><w:t>third</w:t><w:tab/><w:t>fourth</w:t></w:r></w:p>"
    )
    text = _extract_office_text(
        _package(
            {
                "word/document.xml": (
                    f'<w:document xmlns:w="{W}"><w:body>{body}</w:body></w:document>'
                )
            }
        )
    )
    assert text.splitlines() == ["first", "second", "third\tfourth"]


def test_escaped_characters_are_read_as_characters() -> None:
    read = _extract_office_text(_docx("Musa &amp; Ngozi saved &lt; 5%"))
    assert read == "Musa & Ngozi saved < 5%"


def test_empty_paragraphs_do_not_become_blank_lines() -> None:
    assert _extract_office_text(_docx("one", "", "   ", "two")).splitlines() == ["one", "two"]


def test_styles_and_fonts_stay_out_of_the_lesson() -> None:
    assert "Calibri" not in _extract_office_text(_docx("Simple Interest"))


def test_slides_are_read_in_the_order_they_are_shown() -> None:
    parts = {
        f"ppt/slides/slide{number}.xml": (
            f'<p:sld xmlns:a="{A}"><a:p><a:r><a:t>slide {number}</a:t></a:r></a:p></p:sld>'
        )
        for number in (1, 2, 10)
    }
    # slide10 sorts before slide2 as a string, which would deal the lesson out
    # of order.
    assert _extract_office_text(_package(parts)).splitlines() == [
        "slide 1",
        "slide 2",
        "slide 10",
    ]


def test_a_package_with_no_document_is_rejected() -> None:
    with pytest.raises(HTTPException) as error:
        _extract_office_text(_package({"docProps/app.xml": "<Properties/>"}))
    assert error.value.status_code == 400


def test_something_that_is_not_a_zip_is_rejected() -> None:
    with pytest.raises(HTTPException) as error:
        _extract_office_text(b"this is not a Word document")
    assert error.value.status_code == 400
