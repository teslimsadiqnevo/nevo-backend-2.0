# SCRUM-15: Zero-Tag learner profile schema

## Scope

Implement the first PostgreSQL schema for functional learner profiles without
clinical or diagnostic identifiers.

## Acceptance criteria

1. `learner_profiles` stores exactly one current profile per learner.
2. All six Jira-defined functional dimensions are represented.
3. Every dimension has a `low`, `medium`, or `high` confidence value.
4. Controlled values and numeric ranges are enforced by PostgreSQL.
5. `learner_profile_history` stores versioned profile snapshots with source,
   actor, reason, and timestamp metadata.
6. History records are immutable at database level.
7. Current profile and history lookup indexes are present.
8. No table, column, constraint, index, or enum value contains prohibited
   diagnostic terminology.
9. Alembic can upgrade a clean PostgreSQL database to `head` and downgrade it to
   `base`.
10. Automated contract tests and PostgreSQL integration tests pass in CI.

## Deferred dependency

SCRUM-16 owns the canonical `users` table. A follow-up migration must add the
foreign key from both learner profile tables after that table exists.
