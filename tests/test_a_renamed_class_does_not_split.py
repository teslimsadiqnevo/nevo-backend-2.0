"""Renaming a class must not split its register in two.

The attachment between an uploaded roster row and a live class used to be
the class's folded name. The name is what a school types and the name is
what they change, so a class renamed between confirming an import and
activating it stopped matching: activation built a second class under the
file's old spelling and the rest of the roster landed there. Nobody notices
a class splitting until a register is half empty, which is why this is a
defect rather than the two cosmetic items filed beside it. T18.

These tests are about the wiring that makes the bug impossible - the row
carries an id, the creating path consults it, and the screen the school
reads is not changed by any of it.
"""

from __future__ import annotations

import inspect
import pathlib

from nevo.api import onboarding
from nevo.db.models.onboarding import OnboardingRow


def test_a_row_remembers_its_class_by_id() -> None:
    column = OnboardingRow.__table__.c.class_id
    assert column.nullable, "rows imported before this existed have no id"
    assert [fk.column.table.name for fk in column.foreign_keys] == ["classes"]
    # A deleted class must not take the roster row with it.
    assert all(fk.ondelete == "SET NULL" for fk in column.foreign_keys)


def test_committing_classes_pins_every_countable_row() -> None:
    source = inspect.getsource(onboarding._commit_classes)
    assert "source.class_id = resolved.id" in source
    # Never re-pin: re-running this must not move a child out of the class
    # they are already in.
    assert "source.class_id is not None" in source


def test_committing_classes_finds_a_renamed_class_by_id() -> None:
    """The fix itself: look the pinned class up by id, not by name."""
    source = inspect.getsource(onboarding._commit_classes)
    assert "await session.get(Class, source.class_id)" in source
    assert 'derived.normalised_name in existing or derived.normalised_name in pinned' in source


def test_attachment_prefers_the_id_and_falls_back_to_the_name() -> None:
    source = inspect.getsource(onboarding._create_person)
    assert "await session.get(Class, row.class_id)" in source
    # The fallback has to stay for rows that predate the column.
    assert 'classes.get(row.normalised_class_name or "")' in source


def test_the_school_facing_derivation_is_untouched() -> None:
    """_derived_classes also feeds the onboarding screen's own counts.

    Skipping pinned rows there would show a school no classes at all after
    they had confirmed their import, which is a worse bug than the one being
    fixed. Pinning belongs to the path that *creates* classes, not the one
    that describes them.
    """
    source = inspect.getsource(onboarding._derived_classes)
    assert "class_id" not in source


def test_the_migration_refuses_to_guess_at_a_split_register() -> None:
    path = (
        pathlib.Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "20261120_0144_onboarding_row_keeps_its_class_id.py"
    )
    source = path.read_text()
    # Backfill only an unambiguous match; report the rest rather than pick.
    assert "candidate.matches = 1" in source
    assert "COUNT(DISTINCT c.id) > 1" in source
    assert "down_revision = \"20261115_0143\"" in source
