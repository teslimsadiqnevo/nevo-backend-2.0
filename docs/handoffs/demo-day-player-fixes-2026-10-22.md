# Demo-day player follow-up: 22 October 2026

## Progress/adapt failures

Identified and reproduced a PostgreSQL lock inversion: progress/session writes held
`users FOR UPDATE` while adaptation/signal writes held the sitting and needed a
foreign-key key-share lock on the user. The isolated regression forces that
interleaving: the old lock reproduces a deadlock, the new lock completes.
Player serialization now uses `FOR NO KEY UPDATE`, retaining serialization without
blocking those FK checks. Production database statistics reported 43 deadlocks at
inspection. These are database-wide statistics, not proof that each supplied
incident ID is the same exception; that mapping still requires Render tracebacks.

Two concurrent test waves exercised 12 progress HTTP writes, 12 adaptation HTTP
calls and 12 real signal-repository flushes without failure. Partial progress
writes now preserve existing cursor/assignment values when those fields are
omitted. An unsaved position from a genuinely failed request cannot be recreated
from nothing; clients should retain and retry unacknowledged saves.

## Completed review recovery

The signal upsert previously overwrote completion status, end time, cursor and
counters from every incoming snapshot. A delayed in-progress batch could reopen
a completed sitting. Amina's progress was completed at 19:27:13 UTC while its
linked sitting was in progress with no end time, exactly this inconsistent state.

Signal snapshots now preserve terminal sittings and monotonic counters. Session
ownership and existing lesson binding are checked before accepting a conflicting
upsert. Review entry repairs a reopened linked sitting using durable progress
completion, rather than returning `completed_session_unavailable` or resetting
the lesson. It does not invent answers or mastery.

Amina's original sitting `f5790a46-16f1-40f8-a8b2-6be0a144b5d3` was repaired from
that existing completion record. Her authentication, onboarding, answers and
baseline were not changed. Progress/adapt handler replay against her real stored
data passed with all replay writes rolled back.

## Activity safety and formatting

`InteractiveActivityVariant.safety` is an optional string, omitted when absent.
It carries source-authored safety instructions and should be displayed before
the practical steps. Existing activities without it remain valid. Stored lesson
reads and offline packages extract a missing safety line only from that activity's
own source body, never another activity or generic generated copy. Parser-side
source verification prevents fabricated safety text being retained.

Osmosis section 4 now stores the original safety warning, retains all six steps,
and begins its outcome with "The strip". Capitalization does not rewrite scientific
notation such as pH. The simplified practice section now has five separate
paragraphs, with identical words and unchanged review provenance. Future depth
responses preserve numbered-item paragraph breaks too.

## Probe ordering

The served probe order is deterministic for pupil + item and independent of the
answer. Amina's recorded items have correct-option positions `1, 2, 3, 3, 2`.
Across all eight active items in her school, her presentation positions are:
first: 2, second: 4, third: 2. One item having the answer first is expected; forcing
the first item to be incorrect in its first position would introduce a new bias.

## Delivery

315 focused intelligence/content-parsing/signal tests passed, including the
forced old-lock deadlock and new-lock regression. Ruff and targeted mypy pass.
No schema migration is required. The code needs deployment to prevent recurrence
and expose the new safety field; the targeted data repairs are already applied.
The frontend repository was not modified. Yinka's re-established assignments were
left intact. Public production re-run is needed after deployment; this document
does not claim all supplied incident IDs have been individually diagnosed.
