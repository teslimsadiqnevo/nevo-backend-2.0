"""The reset script's classification has to stay complete and correct.

Two ways this script could do real harm. It could delete something a lesson
checks before it will start - consent, enrolment, the onboarding modules - and
leave a child who signs in and is refused at the door with a 409, which from
the console looks like a broken lesson. Or a new table holding a child's work
could appear and be silently left behind, so the reset quietly stops being a
reset.

The guard against the second is that every student-scoped table must be
classified one way or the other, checked at every run. These tests hold the
first list to the things a lesson actually gates on.
"""

from __future__ import annotations

import importlib.util
import pkgutil
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "reset_student_progress.py"


@pytest.fixture(scope="module")
def script():
    """The script's module-level declarations, without running main()."""
    source = SCRIPT.read_text().replace("asyncio.run(main())", "")
    spec = importlib.util.spec_from_loader("reset_student_progress", loader=None)
    module = importlib.util.module_from_spec(spec)
    exec(compile(source, str(SCRIPT), "exec"), module.__dict__)
    return module


def _student_tables() -> set[str]:
    import nevo.db.models as models
    from nevo.db.base import Base

    for found in pkgutil.iter_modules(models.__path__):
        importlib.import_module(f"nevo.db.models.{found.name}")
    return {
        table.name
        for table in Base.metadata.sorted_tables
        if any(column.name == "student_id" for column in table.columns)
    }


def test_every_student_scoped_table_is_classified(script) -> None:
    """A table nobody has classified is a table nobody has thought about."""
    assert script.unclassified() == set(), (
        "these tables hold a student_id and the reset script has no opinion "
        f"about them: {sorted(script.unclassified())}"
    )


def test_the_three_lists_do_not_overlap(script) -> None:
    progress, support, kept = set(script.PROGRESS), set(script.SUPPORT), set(script.KEPT)
    assert progress & kept == set()
    assert progress & support == set()
    assert support & kept == set()


def test_nothing_a_lesson_gates_on_is_ever_deleted(script) -> None:
    """The 409-at-the-door list, from the seed script that had to satisfy it."""
    gates = {
        "consent_records",
        "student_class_enrollments",
        "learner_profiles",
        "student_onboarding_grants",
    }
    removable = set(script.PROGRESS) | set(script.SUPPORT)
    assert gates & removable == set(), (
        f"{sorted(gates & removable)} would be deleted, leaving a child who signs in and is refused"
    )
    assert gates <= set(script.KEPT)


def test_an_assigned_lesson_stays_assigned(script) -> None:
    """The point of a reset is to do the lesson again."""
    assert "lesson_assignments" in script.KEPT
    assert "lesson_assignments" not in script.PROGRESS


def test_a_teachers_own_note_is_not_treated_as_progress(script) -> None:
    """escalations carries a non-nullable teacher_note and a routed-to person."""
    assert "escalations" not in script.PROGRESS
    assert "escalations" in script.SUPPORT


def test_safety_and_audit_records_are_not_progress(script) -> None:
    for table in (
        "content_safety_events",
        "student_record_events",
        "learner_purge_receipts",
        "learner_profile_history",
        "student_enrollment_history",
        "consent_refusals",
        "age_checks",
    ):
        assert table in script.KEPT, table
        assert table not in script.PROGRESS, table


def test_what_the_child_did_is_actually_removed(script) -> None:
    """The reset has to reset something, or it is not one."""
    for table in (
        "lesson_question_attempts",
        "lesson_sessions",
        "lesson_progress",
        "student_concept_mastery",
        "student_concept_level_mastery",
    ):
        assert table in script.PROGRESS, table


def test_the_append_only_table_is_left_alone_and_said_so(script) -> None:
    """signal_events cannot be deleted, and does not need to be.

    A database trigger refuses the delete outright - the raw record of what a
    child did is audit evidence. Attempting it took the whole reset down with
    it the first time, which the single transaction rolled back.

    It costs the reset nothing, because every read of those events joins
    through the child's lesson sessions, and those do go. The accommodation
    repository returns an empty aggregate as soon as a child has no sessions.
    """
    assert "signal_events" in script.APPEND_ONLY
    assert "signal_events" not in script.PROGRESS
    assert "signal_events" not in script.KEPT
    source = SCRIPT.read_text()
    assert "append-only" in source
    # The run says what it left behind rather than looking like it forgot.
    assert "row(s) stay" in source


def test_billing_is_not_the_child_s_to_lose(script) -> None:
    assert "ai_gateway_calls" in script.KEPT


def test_it_will_not_delete_anything_without_being_told_twice(script) -> None:
    source = SCRIPT.read_text()
    # Dry run by default.
    assert '"--apply"' in source
    assert "if not args.apply:" in source
    # And a real child needs saying so out loud.
    assert '"--i-know-this-is-a-real-child"' in source
    assert "TEST_SCHOOL_ID" in source


def test_support_flags_cannot_be_cleared_for_a_real_child(script) -> None:
    source = SCRIPT.read_text()
    guard = source[source.index("--also-clear-support-flags is for test children only") :]
    assert "teacher's own note" in guard


def test_the_classification_lists_are_not_accidentally_empty(script) -> None:
    assert len(script.PROGRESS) >= 14
    assert len(script.KEPT) >= 20
    assert len(script.SUPPORT) >= 4
    assert _student_tables() >= set(script.PROGRESS)
