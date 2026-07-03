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
