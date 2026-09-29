class TeacherAssignmentError(Exception):
    code = "teacher_assignment_error"
    public_message = "The teacher assignment operation could not be completed."


class AssignmentNotFoundError(TeacherAssignmentError):
    code = "assignment_not_found"
    public_message = "The requested teacher assignment was not found."


class ClassNotFoundError(TeacherAssignmentError):
    code = "class_not_found"
    public_message = "The requested class was not found."


class TeacherNotFoundError(TeacherAssignmentError):
    code = "teacher_not_found"
    public_message = "The requested teacher was not found."


class AssignmentConflictError(TeacherAssignmentError):
    code = "assignment_conflict"
    public_message = "This teacher already has an active assignment to the class."


class PrimaryTeacherExistsError(TeacherAssignmentError):
    code = "primary_teacher_exists"
    public_message = "This class already has an active primary teacher."


class TeacherNotAssignedError(TeacherAssignmentError):
    code = "teacher_not_assigned"
    public_message = "The teacher is not assigned to this class."


class MissingSchoolContextError(TeacherAssignmentError):
    code = "missing_school_context"
    public_message = "A school context is required for teacher assignments."


class SubjectRequiredError(TeacherAssignmentError):
    """An assignment names a subject, because that is what it records.

    Teacher-and-class was never the fact anybody needed. Who teaches what is,
    and without the subject the record cannot answer it.
    """

    code = "subject_required"
    public_message = "Choose which subject this teacher teaches to this class."


class SubjectNotOnTeacherError(TeacherAssignmentError):
    """The teacher does not hold this subject.

    Refused rather than added silently. A teacher's subject list is a fact
    about that person, and widening it as a side effect of an assignment means
    nobody can tell what they were actually hired to teach.
    """

    code = "subject_not_on_teacher"
    public_message = (
        "That subject is not on this teacher's list. Add it to the teacher first, "
        "or pick one she already teaches."
    )


class SubjectNotOnClassError(TeacherAssignmentError):
    """The class's scheme of work does not include this subject.

    This is the refusal that earns the rule. It is where a school discovers
    that its own class setup is incomplete, which is worth finding at the
    moment somebody assigns a teacher rather than a term later when a report
    has nothing to group by.
    """

    code = "subject_not_on_class"
    public_message = (
        "That subject is not on this class's list. Add it to the class first, so "
        "the class and the teacher agree about what is taught."
    )
