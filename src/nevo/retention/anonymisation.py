import secrets
from datetime import datetime

from nevo.db.models.account import User
from nevo.domain.accounts.vocabulary import UserStatus

ANONYMISED_FIRST_NAME = "Former"
ANONYMISED_LAST_NAME = "Student"


def anonymise_student(student: User, *, now: datetime) -> None:
    """Strip a student's direct identifiers in place.

    Learning records keep pointing at the same row, so aggregate reporting
    still works, but nothing on the row identifies a person. Shared by the
    SENCo's manual delete and the scheduled retention sweep so both produce
    exactly the same result.
    """
    student.first_name = ANONYMISED_FIRST_NAME
    student.last_name = ANONYMISED_LAST_NAME
    student.email = None
    student.login_identifier = f"deleted-{secrets.token_hex(8)}"
    student.password_hash = None
    student.pin_hash = None
    student.sso_external_id = None
    student.baseline_profile = {}
    student.engine_config = {}
    student.preferences = {}
    student.status = UserStatus.DEACTIVATED
    student.anonymised_at = now
    if student.deactivated_at is None:
        student.deactivated_at = now
