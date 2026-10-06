"""A small Markdown-to-HTML renderer, enough for these reports.

Deliberately not a full implementation. It handles what the report actually
uses - headings, tables, lists, fenced code, blockquotes, bold, italic,
inline code, horizontal rules - and nothing else, because a general Markdown
library is a dependency this repo does not otherwise need.
"""

from __future__ import annotations

import html
import re
import sys
from pathlib import Path

CSS = """
@page { size: A4; margin: 18mm 16mm 20mm; }
body { font: 10.5pt/1.55 -apple-system, "Helvetica Neue", Helvetica, Arial, sans-serif;
       color: #1a1a1a; margin: 0; }
h1 { font-size: 20pt; margin: 0 0 2pt; letter-spacing: -0.3pt; }
h2 { font-size: 13.5pt; margin: 22pt 0 6pt; padding-bottom: 3pt;
     border-bottom: 1px solid #d8d8d8; page-break-after: avoid; }
h3 { font-size: 11.5pt; margin: 15pt 0 4pt; page-break-after: avoid; }
p { margin: 0 0 7pt; }
ul, ol { margin: 0 0 8pt; padding-left: 17pt; }
li { margin: 0 0 3pt; }
table { border-collapse: collapse; width: 100%; margin: 6pt 0 11pt;
        font-size: 9.5pt; page-break-inside: avoid; }
th { text-align: left; background: #f4f4f4; border-bottom: 1.5px solid #c8c8c8;
     padding: 5pt 7pt; font-weight: 600; }
td { border-bottom: 1px solid #e8e8e8; padding: 5pt 7pt; vertical-align: top; }
code { font: 9.3pt/1.4 "SF Mono", Menlo, Consolas, monospace;
       background: #f3f3f3; padding: 1pt 3.5pt; border-radius: 2.5pt; }
pre { background: #f7f7f7; border: 1px solid #e4e4e4; border-radius: 4pt;
      padding: 8pt 10pt; overflow-x: auto; page-break-inside: avoid;
      margin: 0 0 10pt; }
pre code { background: none; padding: 0; font-size: 9pt; }
blockquote { margin: 0 0 9pt; padding: 7pt 11pt; background: #f6f8fa;
             border-left: 3px solid #b8b8b8; }
blockquote p:last-child { margin-bottom: 0; }
hr { border: none; border-top: 1px solid #dcdcdc; margin: 16pt 0; }
strong { font-weight: 650; }
em { font-style: italic; }
.subtitle { color: #5a5a5a; font-size: 10pt; margin: 0 0 14pt; }
"""


def inline(text: str) -> str:
    out = html.escape(text, quote=False)
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    out = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])", r"<em>\1</em>", out)
    out = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', out)
    return out


def render(markdown: str) -> str:
    lines = markdown.split("\n")
    body: list[str] = []
    index = 0
    list_open: str | None = None

    def close_list() -> None:
        nonlocal list_open
        if list_open:
            body.append(f"</{list_open}>")
            list_open = None

    while index < len(lines):
        line = lines[index]

        if line.startswith("```"):
            close_list()
            index += 1
            block: list[str] = []
            while index < len(lines) and not lines[index].startswith("```"):
                block.append(html.escape(lines[index], quote=False))
                index += 1
            body.append("<pre><code>" + "\n".join(block) + "</code></pre>")
            index += 1
            continue

        if line.startswith("|") and index + 1 < len(lines) and re.match(
            r"^\|[\s:|-]+\|$", lines[index + 1].strip()
        ):
            close_list()
            header = [cell.strip() for cell in line.strip().strip("|").split("|")]
            index += 2
            rows: list[list[str]] = []
            while index < len(lines) and lines[index].startswith("|"):
                rows.append(
                    [cell.strip() for cell in lines[index].strip().strip("|").split("|")]
                )
                index += 1
            head = "".join(f"<th>{inline(cell)}</th>" for cell in header)
            out = [f"<table><thead><tr>{head}</tr></thead><tbody>"]
            for row in rows:
                cells = "".join(f"<td>{inline(cell)}</td>" for cell in row)
                out.append(f"<tr>{cells}</tr>")
            out.append("</tbody></table>")
            body.append("".join(out))
            continue

        heading = re.match(r"^(#{1,4})\s+(.*)$", line)
        if heading:
            close_list()
            level = len(heading.group(1))
            body.append(f"<h{level}>{inline(heading.group(2))}</h{level}>")
            index += 1
            continue

        if re.match(r"^(---+|\*\*\*+)\s*$", line):
            close_list()
            body.append("<hr>")
            index += 1
            continue

        if line.startswith("> "):
            close_list()
            quote: list[str] = []
            while index < len(lines) and lines[index].startswith(">"):
                quote.append(lines[index].lstrip(">").strip())
                index += 1
            paragraphs = "".join(
                f"<p>{inline(part)}</p>" for part in "\n".join(quote).split("\n\n") if part.strip()
            )
            body.append(f"<blockquote>{paragraphs}</blockquote>")
            continue

        bullet = re.match(r"^\s*[-*]\s+(.*)$", line)
        number = re.match(r"^\s*\d+\.\s+(.*)$", line)
        if bullet or number:
            wanted = "ul" if bullet else "ol"
            if list_open != wanted:
                close_list()
                body.append(f"<{wanted}>")
                list_open = wanted
            text = (bullet or number).group(1)
            index += 1
            # A wrapped list item continues on the next indented line.
            while (
                index < len(lines)
                and lines[index].strip()
                and not re.match(r"^\s*([-*]|\d+\.)\s+", lines[index])
                and not lines[index].startswith(("#", "|", "```", ">", "---"))
            ):
                text += " " + lines[index].strip()
                index += 1
            body.append(f"<li>{inline(text)}</li>")
            continue

        if not line.strip():
            close_list()
            index += 1
            continue

        close_list()
        paragraph = [line]
        index += 1
        while (
            index < len(lines)
            and lines[index].strip()
            and not lines[index].startswith(("#", "|", "```", ">", "-", "*", "---"))
            and not re.match(r"^\s*\d+\.\s", lines[index])
        ):
            paragraph.append(lines[index])
            index += 1
        body.append(f"<p>{inline(' '.join(paragraph))}</p>")

    close_list()
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<style>{CSS}</style></head><body>" + "".join(body) + "</body></html>"
    )


if __name__ == "__main__":
    source = Path(sys.argv[1])
    Path(sys.argv[2]).write_text(render(source.read_text()), encoding="utf-8")
