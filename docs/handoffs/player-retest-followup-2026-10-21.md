# Player retest follow-up: Yinka's two messages

Backend only. Source changes require deployment; the stored-data repairs below have already been applied. No migration is required.

## Message 1

- Adapt/progress errors: completion and queue writes were made atomic in b2dca76. This follow-up also corrects the transaction-pooler engine settings: asyncpg's cache was disabled, but SQLAlchemy's independent prepared-statement cache was not. Transaction mode now disables both caches, uses unique statement names and delegates pooling to the pooler. Session/direct mode retains its connection pool. This is a concrete configuration correction, not proof of the cause of incidents f76c126d23da, a0c964056832, bd9778f5591e or 687b0664ab9e. See the [SQLAlchemy guidance](https://docs.sqlalchemy.org/en/20/dialects/postgresql.html#prepared-statement-cache).
- The HTTP/SQL regression test now submits three distinct, sufficiently timed correct answers without hints, verifies scaffolding changes from strong to standard, and exercises 17 successful adaptation calls. This uses a disposable local database, not the deployed service.
- Socratic hand-off now returns the failed question's stored guidedQuestions, not generic concept-name templates. If no authored/generated guided questions exist, no fictitious dialogue is supplied.
- Option ordering now includes each option's content as well as the question seed and value. Values/keys do not change and repeated reads remain stable. Osmosis's first three correct positions are now 2, 3 and 2; stable random ordering is not a promise that adjacent questions can never share an order.
- Reading splitting now also handles a newline or blank line between a list marker and its instruction. Eighteen stored sections were re-chunked; unchanged bodies and exact text offsets are preserved. Osmosis has no remaining dangling list-marker chunks.
- The option refresh normalised 287 checkpoint sections and assessments in 16 lessons. These are presentation-order changes, not newly discovered question-classification failures.

## Message 2

- Reopening a completed lesson returns the completed sitting with reviewMode=true, reviewOfSessionId, completedAt and segmentPosition=0. It does not create a new unfinished attempt or reset completion. The frontend must open its review view rather than make in-lesson adaptation requests against the ended sitting.
- Late/review progress writes preserve completed status and the original completion cursor. Dashboard recentProgress also carries completedAt. The original attempts remain readable using the returned session ID.
- If a completion record exists but its completed sitting is missing, session opening returns 409 completed_session_unavailable rather than silently making the lesson unfinished.
- A finish request with no marked answers still returns not_attempted and keeps the sitting in progress. That is distinct from reviewing a previously completed lesson. No new completion/mastery evidence is invented.
- Two misses without a usable comparison baseline can still fall below the engine's multi-signal threshold. That existing guard was not relaxed. The separate three-miss hand-off uses the question's actual guided questions. If two misses must always offer a hint regardless of other evidence, product needs to explicitly distinguish question help from the current adaptation guard.

## Verification

The broader regression run passed 364 tests. The final focused run passed 20 player, connection-configuration and chunking tests, including injected queue rollback/retry, completed review, exact guided prompts, support withdrawal and no-answer completion semantics. A deployed browser retest is still needed before treating the four reported intermittent incidents as closed. No frontend files, teacher approvals or provider credits were changed.
