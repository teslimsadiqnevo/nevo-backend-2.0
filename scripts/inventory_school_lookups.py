"""List every place the backend resolves something by matching on a school.

/me, Phase 0. For an account with no school each of these compares against
NULL, matches no rows and succeeds, so the learner gets an empty answer and
nothing reports a problem. The route guard (nevo.api.account_scope) closes
that at the boundary; this inventory is the list the sweep works from, so the
size of the work is known before it starts rather than discovered inside it.

A "lookup" here is a comparison (``==``, ``!=``, ``in``, ``.in_()``) in which
one side is a ``school_id`` / ``school_code`` attribute or name, or
``School.id``. Model definitions and migrations are not lookups and are
skipped.

Every lookup is put in one of four areas by the module it lives in:

  school    school admin, teachers, SSO, invites, permissions  -> route guard
  billing   billing, licences, payments                         -> route guard
  learner   learner surfaces, onboarding, consent, mastery      -> read each one
  unclassified                                                  -> triage

Usage:
  .venv/bin/python scripts/inventory_school_lookups.py            # every lookup
  .venv/bin/python scripts/inventory_school_lookups.py --summary  # counts only
  .venv/bin/python scripts/inventory_school_lookups.py --area unclassified
"""

from __future__ import annotations

import argparse
import ast
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "src" / "nevo"
SKIP_DIRS = {"db/models", "__pycache__"}

SCHOOL_NAMES = {"school_id", "school_code"}

# First match wins, so the more specific fragments come first.
AREAS: list[tuple[str, tuple[str, ...]]] = [
    (
        "learner",
        (
            "api/product_learning.py",
            "api/onboarding.py",
            "api/student_entry.py",
            "api/out_of_school.py",
            "api/learning_readiness.py",
            "api/mastery.py",
            "api/ask_nevo.py",
            "api/paper_work.py",
            "api/consent.py",
            "api/written_consent.py",
            "api/age_checks.py",
            "api/content.py",
            "api/deferred_media.py",
            "api/subjects.py",
            "consent/",
            "mastery/",
            "ask_nevo/",
            "intelligence/learning_runtime.py",
            "intelligence/progression.py",
            "intelligence/comprehension.py",
            "intelligence/reviews.py",
            "intelligence/adaptation",
            "content_parsing/",
            "subjects/",
            "learner_profiles/",
        ),
    ),
    (
        "billing",
        ("billing", "licences", "payments/"),
    ),
    (
        "school",
        (
            "api/product_admin.py",
            "api/admin.py",
            "api/permissions.py",
            "api/learning_support",
            "api/insights.py",
            "api/import_templates.py",
            "api/lesson_review.py",
            "api/teacher_assignments.py",
            "api/sso.py",
            "api/parents.py",
            "api/parent_rights.py",
            "sso/",
            "permissions/",
            "teacher_assignments/",
            "parents/",
            "invite",
        ),
    ),
]


@dataclass(frozen=True)
class Lookup:
    path: str
    line: int
    area: str
    source: str


def _names_a_school(node: ast.AST) -> bool:
    if isinstance(node, ast.Attribute):
        if node.attr in SCHOOL_NAMES:
            return True
        # School.id
        return (
            node.attr == "id"
            and isinstance(node.value, ast.Name)
            and node.value.id == "School"
        )
    if isinstance(node, ast.Name):
        return node.id in SCHOOL_NAMES
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        # X.school_id.in_(...)
        return node.func.attr == "in_" and _names_a_school(node.func.value)
    return False


def _is_lookup(node: ast.AST) -> bool:
    if isinstance(node, ast.Compare):
        if not any(isinstance(op, (ast.Eq, ast.NotEq, ast.In, ast.NotIn)) for op in node.ops):
            return False
        return any(_names_a_school(side) for side in (node.left, *node.comparators))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        return node.func.attr == "in_" and _names_a_school(node.func.value)
    return False


def area_for(relative: str) -> str:
    for area, fragments in AREAS:
        if any(fragment in relative for fragment in fragments):
            return area
    return "unclassified"


def scan() -> list[Lookup]:
    found: list[Lookup] = []
    for file in sorted(SOURCE.rglob("*.py")):
        relative = file.relative_to(SOURCE).as_posix()
        if any(skip in relative for skip in SKIP_DIRS):
            continue
        text = file.read_text()
        lines = text.splitlines()
        tree = ast.parse(text, filename=str(file))
        seen: set[int] = set()
        for node in ast.walk(tree):
            if not _is_lookup(node) or node.lineno in seen:
                continue
            seen.add(node.lineno)
            found.append(
                Lookup(
                    path=f"src/nevo/{relative}",
                    line=node.lineno,
                    area=area_for(relative),
                    source=lines[node.lineno - 1].strip(),
                )
            )
    return sorted(found, key=lambda item: (item.area, item.path, item.line))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--summary", action="store_true", help="print counts only")
    parser.add_argument(
        "--area",
        choices=["school", "billing", "learner", "unclassified"],
        help="only this area",
    )
    args = parser.parse_args(argv)

    lookups = scan()
    if args.area:
        lookups = [item for item in lookups if item.area == args.area]

    if not args.summary:
        for item in lookups:
            print(f"{item.path}:{item.line}\t{item.area}\t{item.source}")
        print()

    counts = Counter(item.area for item in lookups)
    for area in ("school", "billing", "learner", "unclassified"):
        if area in counts:
            print(f"{area:>13}  {counts[area]}")
    print(f"{'total':>13}  {len(lookups)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
