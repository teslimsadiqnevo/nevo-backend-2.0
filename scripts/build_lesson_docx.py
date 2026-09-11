"""Render a lesson written in Markdown into the .docx a teacher would upload.

The fixtures are authored as Markdown because that is what a person can read
and edit in a diff. What the pipeline actually receives is a Word document, so
the two have to exist side by side and the .docx has to be built from the
Markdown rather than drifting from it.

    python scripts/build_lesson_docx.py tests/fixtures/lessons/*.md

This writes a minimal but valid WordprocessingML package by hand. Word, Pages
and Google Docs all open it, and it avoids a dependency that only ever runs
here.
"""

from __future__ import annotations

import argparse
import io
import re
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
PKG_RELS = "http://schemas.openxmlformats.org/package/2006/relationships"
DOC_RELS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

OOXML = "application/vnd.openxmlformats-officedocument.wordprocessingml"

CONTENT_TYPES = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="{OOXML}.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="{OOXML}.styles+xml"/>
</Types>"""

ROOT_RELS = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="{PKG_RELS}">
<Relationship Id="rId1" Type="{DOC_RELS}/officeDocument" Target="word/document.xml"/>
</Relationships>"""

DOCUMENT_RELS = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="{PKG_RELS}">
<Relationship Id="rId1" Type="{DOC_RELS}/styles" Target="styles.xml"/>
</Relationships>"""


def _style(style_id: str, name: str, *, size: int, bold: bool, mono: bool = False) -> str:
    fonts = '<w:rFonts w:ascii="Courier New" w:hAnsi="Courier New"/>' if mono else ""
    return (
        f'<w:style w:type="paragraph" w:styleId="{style_id}">'
        f'<w:name w:val="{name}"/>'
        f'<w:pPr><w:spacing w:before="120" w:after="120"/></w:pPr>'
        f"<w:rPr>{fonts}{'<w:b/>' if bold else ''}"
        f'<w:sz w:val="{size}"/></w:rPr></w:style>'
    )


STYLES = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="{W}">
{_style("Normal", "Normal", size=22, bold=False)}
{_style("Title", "Title", size=44, bold=True)}
{_style("Heading1", "heading 1", size=32, bold=True)}
{_style("Equation", "Equation", size=22, bold=False, mono=True)}
</w:styles>"""


def _runs(text: str) -> str:
    """Split `**bold**` spans into their own runs, like a person typing."""

    runs = []
    for index, part in enumerate(re.split(r"\*\*(.+?)\*\*", text)):
        if not part:
            continue
        bold = "<w:b/>" if index % 2 else ""
        runs.append(
            f'<w:r><w:rPr>{bold}</w:rPr><w:t xml:space="preserve">{escape(part)}</w:t></w:r>'
        )
    return "".join(runs)


def _paragraph(text: str, style: str = "Normal") -> str:
    return f'<w:p><w:pPr><w:pStyle w:val="{style}"/></w:pPr>{_runs(text)}</w:p>'


def _body(markdown: str) -> str:
    paragraphs: list[str] = []
    pending: list[str] = []

    def flush() -> None:
        if pending:
            paragraphs.append(_paragraph(" ".join(pending)))
            pending.clear()

    for raw in markdown.splitlines():
        line = raw.rstrip()
        if not line.strip():
            flush()
        elif line.startswith("# "):
            flush()
            paragraphs.append(_paragraph(line[2:], "Title"))
        elif line.startswith("## "):
            flush()
            paragraphs.append(_paragraph(line[3:], "Heading1"))
        elif line.startswith("    "):
            # An equation on its own line. Word keeps it on its own line too,
            # which is what lets the parse see one step at a time.
            flush()
            paragraphs.append(_paragraph(line.strip(), "Equation"))
        elif line.startswith("- "):
            # A bullet that wraps in the source is still one bullet, so let
            # the lines under it accumulate rather than closing it here.
            flush()
            pending.append(f"• {line[2:]}")
        elif re.match(r"^(Step \d+\.|\d+\. )", line):
            flush()
            pending.append(line)
        else:
            pending.append(line.strip())
    flush()
    return "".join(paragraphs)


def render(markdown: str) -> bytes:
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{W}"><w:body>{_body(markdown)}'
        '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/></w:sectPr>'
        "</w:body></w:document>"
    )
    raw = io.BytesIO()
    # A fixed date keeps the bytes stable, so rebuilding an unchanged lesson
    # does not show up as a diff.
    stamp = (2026, 1, 1, 0, 0, 0)
    with zipfile.ZipFile(raw, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in (
            ("[Content_Types].xml", CONTENT_TYPES),
            ("_rels/.rels", ROOT_RELS),
            ("word/_rels/document.xml.rels", DOCUMENT_RELS),
            ("word/styles.xml", STYLES),
            ("word/document.xml", document),
        ):
            info = zipfile.ZipInfo(name, date_time=stamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, content)
    return raw.getvalue()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sources", nargs="+", type=Path, help="Markdown lesson sources")
    arguments = parser.parse_args()
    for source in arguments.sources:
        target = source.with_suffix(".docx")
        target.write_bytes(render(source.read_text(encoding="utf-8")))
        print(f"{source} -> {target} ({target.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
