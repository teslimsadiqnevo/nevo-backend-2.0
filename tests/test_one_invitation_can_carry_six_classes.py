"""An invitation carries several classes, and acceptance applies all of them.

T15, approved by Lydia on 20 November. A subject teacher covering six classes
is normal, and one invitation per class meant inviting the same person six
times on day one of setup - six emails, six passwords to set.

The finding that re-sized this: a teacher invitation did not apply its class
at all. On acceptance the invitation's classId was used only to enrol
students; for a teacher it was recorded and ignored, so somebody invited to a
class accepted and arrived attached to nothing. So this builds
attach-on-acceptance and makes it plural at the same time.

The failure Lydia's ask names is a part-applied acceptance: a teacher holding
some of their classes and not others, which looks accepted and is not. That
is what most of these tests are about.
"""

from __future__ import annotations

import inspect

from nevo.api import product_auth
from nevo.api.product_auth import InvitationRequest, InvitedClass
from nevo.db.models.invitation_class import SchoolInvitationClass


def test_an_invitation_can_name_several_classes() -> None:
    field = InvitationRequest.model_fields["classes"]
    assert field.default_factory is list
    assert "InvitedClass" in str(field.annotation)


def test_a_subject_is_required_per_class() -> None:
    """SCRUM-194: a teacher cannot be assigned without one, so an invitation
    naming a class and no subject could never be applied."""
    assert InvitedClass.model_fields["subject_id"].is_required()
    assert SchoolInvitationClass.__table__.c.school_subject_id.nullable is False


def test_one_teacher_can_take_two_subjects_to_one_class() -> None:
    """Which is why the row is a class-and-subject pair, not a class."""
    unique = {
        tuple(sorted(column.name for column in constraint.columns))
        for constraint in SchoolInvitationClass.__table__.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert ("class_id", "invitation_id", "school_subject_id") in unique


def test_everything_is_checked_before_the_invitation_exists() -> None:
    """The teacher accepting cannot fix a deleted class or another school's
    subject, and discovering it then means they set a password and arrived
    holding nothing."""
    source = inspect.getsource(product_auth._checked_invited_classes)
    assert "school_class.school_id != actor.school_id" in source
    assert "school_class.archived_at is not None" in source
    assert "subject.school_id != actor.school_id" in source
    assert '"class_not_found"' in source
    assert '"subject_not_found"' in source
    creation = inspect.getsource(product_auth._create_invitation)
    assert creation.index("_checked_invited_classes(") < creation.index(
        "record = SchoolInvitation("
    )


def test_only_a_teacher_invitation_carries_classes() -> None:
    source = inspect.getsource(product_auth._checked_invited_classes)
    assert '"classes_are_for_teachers"' in source


def test_acceptance_attaches_them_inside_the_activating_transaction() -> None:
    """All of them or none. A teacher holding some of their classes looks
    accepted and is not."""
    source = inspect.getsource(product_auth.accept_join)
    attach_at = source.index("_attach_invited_classes(")
    commit_at = source.index("await session.commit()")
    assert attach_at < commit_at
    # And no commit of its own inside the attach, which would split it.
    attach = inspect.getsource(product_auth._attach_invited_classes)
    assert "commit()" not in attach


def test_the_attachment_is_attributed_to_whoever_invited() -> None:
    """The decision that this person teaches this class was the
    administrator's, not the teacher's for accepting."""
    source = inspect.getsource(product_auth._attach_invited_classes)
    assert "assigned_by_user_id=record.created_by_id" in source


def test_re_accepting_cannot_double_up_assignments() -> None:
    source = inspect.getsource(product_auth._attach_invited_classes)
    assert "removed_at.is_(None)" in source
    assert "in existing" in source


def test_an_invited_teacher_is_not_made_the_primary_teacher() -> None:
    """That is the class's own teacher, and it would collide with whoever
    already holds it."""
    source = inspect.getsource(product_auth._attach_invited_classes)
    # The assignment itself, not the absence of the word - the comment
    # explaining the choice necessarily mentions the role it rejects.
    assert "role=TeacherAssignmentRole.CO_TEACHER," in source
    assert "role=TeacherAssignmentRole.PRIMARY" not in source


def test_the_old_single_class_still_means_what_it_meant() -> None:
    """Invitations already sent were written when a teacher's class was
    recorded and never applied. Changing what they do on acceptance after
    the fact would be a surprise, so classId is read for students only."""
    source = inspect.getsource(product_auth.accept_join)
    assert 'record.class_id and record.role == "student"' in source
