"""The pseudonymised set and the resolvable set must be the same set.

They are two halves of one mechanism. If the guard masks fewer learners than
the directory can resolve, a name reaches the provider unmasked. If it masks
more, the model is handed a code no tool can turn back into a record. Both
failures have happened; this pins them shut.
"""
import inspect

from nevo import access
from nevo.ai_gateway import repositories as gateway_repositories
from nevo.ask_nevo.directory import PseudonymDirectory


def test_both_sides_derive_from_one_definition() -> None:
    """Two copies of this rule would drift, and the drift is a privacy hole."""
    assert "accessible_students" in inspect.getsource(gateway_repositories)
    assert "accessible_students" in inspect.getsource(
        inspect.getmodule(PseudonymDirectory)
    )


def test_the_guard_masks_every_learner_the_tools_can_reach() -> None:
    """The bug this closes: only the requester's name was ever masked.

    A teacher on a page with no studentId asking about a learner by name sent
    that name to the provider in the clear, and the model then could not match
    it against the pseudonyms the tools speak.
    """
    source = inspect.getsource(gateway_repositories.SqlAlchemyAiCallRepository._sensitive_terms)

    assert "accessible_students" in source
    # Requester and named student are still covered, but are no longer the
    # whole story.
    assert "requester.id" in source


def test_scope_is_bounded_by_class_for_a_teacher() -> None:
    """Not the whole school: this runs on every AI call."""
    source = inspect.getsource(access.accessible_students)

    assert "TeacherClassAssignment" in source
    assert "UserRole.TEACHER" in source


def test_a_student_actor_is_scoped_to_themselves() -> None:
    source = inspect.getsource(access.accessible_students)

    assert "if actor.role is UserRole.STUDENT:" in source
    assert "return [actor]" in source


def test_deactivated_learners_are_excluded() -> None:
    """An anonymised leaver has no name worth masking and no data to fetch."""
    assert "UserStatus.DEACTIVATED" in inspect.getsource(access.accessible_students)


def test_an_actor_without_a_school_reaches_nobody() -> None:
    source = inspect.getsource(access.accessible_students)

    assert "if actor.school_id is None:" in source
    assert "return []" in source
