"""Public notices derived from the dependencies installed in this backend release."""

import json
from functools import lru_cache
from html import escape
from importlib import metadata, resources
from pathlib import PurePosixPath

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from pydantic import BaseModel

router = APIRouter(tags=["system"])


class LicenceText(BaseModel):
    name: str
    text: str
    source: str | None = None
    sha256: str | None = None


class DependencyNotice(BaseModel):
    name: str
    version: str
    licence: str
    notices: list[LicenceText]


class LicenceInventory(BaseModel):
    scope: str = "backend"
    backendVersion: str
    frontendIncluded: bool = False
    dependencies: list[DependencyNotice]


@lru_cache(maxsize=1)
def inventory() -> LicenceInventory:
    root = metadata.distribution("nevo-backend")
    pending = []
    for item in root.requires or []:
        requirement = Requirement(item)
        if requirement.marker is None or requirement.marker.evaluate({"extra": ""}):
            pending.append(requirement)
    visited: dict[str, set[str]] = {}
    found = {}
    while pending:
        requirement = pending.pop()
        name = canonicalize_name(requirement.name)
        extras = set(requirement.extras)
        if name in visited and extras <= visited[name]:
            continue
        visited.setdefault(name, set()).update(extras)
        dist = metadata.distribution(name)
        found[name] = dist
        for raw in dist.requires or []:
            child = Requirement(raw)
            if child.marker is None or any(
                child.marker.evaluate({"extra": extra}) for extra in {"", *visited[name]}
            ):
                pending.append(child)
    supplement = resources.files("nevo.legal").joinpath("generated_notices.json")
    extra = json.loads(supplement.read_text(encoding="utf-8")) if supplement.is_file() else {}
    notices = []
    for name, dist in sorted(found.items()):
        licence = dist.metadata.get("License-Expression") or dist.metadata.get("License")
        if not licence:
            licence = (
                "; ".join(
                    value
                    for value in dist.metadata.get_all("Classifier", [])
                    if value.startswith("License ::")
                )
                or "Not declared in package metadata"
            )
        texts = []
        for file in sorted(dist.files or [], key=str):
            path = PurePosixPath(str(file))
            basename = path.name.upper()
            is_notice = basename.startswith(
                ("LICENSE", "LICENCE", "COPYING", "COPYRIGHT", "NOTICE")
            )
            if not is_notice or path.suffix.lower() not in {
                "",
                ".txt",
                ".md",
                ".rst",
                ".apache",
                ".bsd",
            }:
                continue
            content = dist.locate_file(file).read_text()
            texts.append(LicenceText(name=str(path), text=content))
        if not texts:
            texts = [
                LicenceText.model_validate(value)
                for value in extra.get(
                    f"{dist.metadata.get('Name', name).lower()}=={dist.version}", []
                )
            ]
        notices.append(
            DependencyNotice(
                name=dist.metadata.get("Name", name),
                version=dist.version,
                licence=licence,
                notices=texts,
            )
        )
    return LicenceInventory(backendVersion=root.version, dependencies=notices)


def prepared_inventory() -> LicenceInventory:
    data = inventory()
    if any(not item.notices for item in data.dependencies):
        raise HTTPException(503, detail={"code": "licence_inventory_unavailable"})
    return data


@router.get("/legal/third-party-licenses.json", response_model=LicenceInventory)
def licence_json() -> LicenceInventory:
    return prepared_inventory()


@router.get("/legal/third-party-licenses.txt", response_class=PlainTextResponse)
def licence_text() -> PlainTextResponse:
    data = prepared_inventory()
    sections = [
        f"Nevo backend {data.backendVersion}: third-party licences",
        "Scope: backend runtime dependencies and their packaged notices; frontend is not included.",
    ]
    for item in data.dependencies:
        sections.append(f"\n{item.name} {item.version}\n{item.licence}")
        sections.extend(f"\n{notice.name}\n{notice.text}" for notice in item.notices)
        if not item.notices:
            sections.append("No licence text was included in this installed distribution.")
    return PlainTextResponse("\n".join(sections))


@router.get("/legal/third-party-licenses", response_class=HTMLResponse)
def licence_page() -> HTMLResponse:
    data = prepared_inventory()
    rows = []
    for item in data.dependencies:
        texts = "".join(
            f"<details><summary>{escape(notice.name)}</summary>"
            f"<pre>{escape(notice.text)}</pre></details>"
            for notice in item.notices
        )
        if not texts:
            texts = "<p>No licence text was included in this installed distribution.</p>"
        rows.append(
            f"<section><h2>{escape(item.name)} {escape(item.version)}</h2>"
            f"<p>{escape(item.licence)}</p>{texts}</section>"
        )
    body = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Nevo backend third-party licences</title><style>
body{{font:16px/1.6 system-ui,sans-serif;margin:32px auto;padding:0 20px;
max-width:1000px;color:#2b2b2f;background:#f7f1e6}}
h1{{font-size:26px}}h2{{font-size:20px}}section{{border-top:1px solid #9a9ccb;padding:20px 0}}
pre{{white-space:pre-wrap;overflow-wrap:anywhere;font:13px/1.6 monospace}}
a{{color:#3b3f6e}}summary{{cursor:pointer;overflow-wrap:anywhere}}p,h2{{overflow-wrap:anywhere}}
</style></head><body><h1>Backend third-party licences</h1>
<p>Nevo backend release {escape(data.backendVersion)}. Generated from the runtime
dependencies installed in this release, including their packaged licence and notice files.
Frontend dependencies, including sharp and libvips, are not covered by this backend inventory.</p>
<p><a href="/legal/third-party-licenses.txt">Download text</a> ·
<a href="/legal/third-party-licenses.json">Machine-readable inventory</a></p>
{"".join(rows)}</body></html>"""
    return HTMLResponse(
        body,
        headers={
            "Content-Security-Policy": (
                "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'"
            ),
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "public, max-age=3600",
        },
    )
