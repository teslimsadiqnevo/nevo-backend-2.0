# SCRUM-19: Teacher-class assignment system

## Acceptance criteria

1. Teachers and classes have a school-scoped many-to-many relationship.
2. Assignment roles are exactly `primary` and `co_teacher`.
3. A class has at most one active primary teacher.
4. A teacher has at most one active assignment to the same class.
5. Removal and reassignment preserve history; reassignment links the previous
   row to its replacement.
6. Only active teacher accounts from the same school can be assigned.
7. Roster-scoped administrators can create, reassign, remove, and inspect
   assignments.
8. Teachers can retrieve their current classes through a dedicated `me`
   endpoint.
9. IT/SSO-scoped staff can trigger roster synchronization.
10. Missing or incomplete roster mappings produce an explicit manual fallback
    rather than a false success.
11. A reusable current-assignment guard is available for the C.7 lesson
    assignment constraint.
12. Unit, API, migration, model-contract, and PostgreSQL tests cover the
    behavior and database invariants.

## API surface

- `POST /api/v1/teacher-class-assignments`
- `POST /api/v1/teacher-class-assignments/{assignment_id}/reassign`
- `DELETE /api/v1/teacher-class-assignments/{assignment_id}`
- `GET /api/v1/teachers/me/classes`
- `GET /api/v1/teachers/{teacher_id}/classes`
- `GET /api/v1/classes/{class_id}/teachers`
- `POST /api/v1/teacher-class-assignments/roster-sync`

## Dependency

SCRUM-19 builds on the core school, user, and class schema from SCRUM-16,
authenticated principals from SCRUM-17, and scope checks from SCRUM-18.
