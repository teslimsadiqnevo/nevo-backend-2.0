# ADR 0005: Historical teacher-class assignments

- Status: Accepted for SCRUM-19
- Date: 2026-07-03
- Owners: Nevo backend team

## Context

Teachers can belong to multiple classes and classes can have a primary teacher
plus co-teachers. The relationship is school-scoped, must support roster
imports and manual administration, and must preserve assignment history.
Future lesson assignment must also be able to prove that a teacher currently
belongs to the target class.

## Decision

- `teacher_class_assignments` is the authoritative many-to-many relationship
  between teachers and classes.
- Roles are exactly `primary` and `co_teacher`.
- Sources are exactly `manual` and `roster_sync`, with an optional external
  source reference.
- Removing an assignment sets `removed_at`; rows are never deleted by the
  application.
- Reassignment closes the current row, creates a replacement, and links the
  previous row through `replaced_by_assignment_id`.
- Partial unique indexes enforce one active teacher-class pair and one active
  primary teacher per class while allowing historical rows.
- Repository writes lock the class and validate that both class and active
  teacher belong to the authenticated school.
- Teachers use `GET /api/v1/teachers/me/classes`. Roster-scoped administrators
  can manage assignments and inspect teachers or classes.
- `require_teacher_assignment` is the reusable policy boundary for C.7 lesson
  assignment. Lesson APIs will call it before allowing a teacher to target a
  class.
- Roster synchronization is behind a provider port. Until an SSO-specific
  provider is installed, the API explicitly returns
  `manual_fallback_required` instead of pretending a synchronization occurred.

## Consequences

- Current assignment queries remain small and deterministic while history is
  retained for audits.
- Database constraints protect invariants even if concurrent requests bypass
  application-level checks.
- Roster providers can be added without changing assignment policy or API
  response contracts.
- The lesson service can adopt the C.7 guard without duplicating assignment
  queries.
