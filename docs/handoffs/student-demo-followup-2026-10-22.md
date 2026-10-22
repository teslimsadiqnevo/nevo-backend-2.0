# Student demo follow-up: 22 October

Backend only. Deploy the new main commit; no migration is needed. Source-data repairs described below have already been applied. No frontend files were edited.

## 1. Connection pool and slowdown

The prior transaction-mode branch used NullPool, so API sessions opened fresh client connections. That change did remove API-side pooling for port 6543. It is now restored to ten pooled connections with up to ten overflow connections, while retaining zero asyncpg/SQLAlchemy statement caches and unique statement names in transaction mode. Direct/session mode keeps its existing cache behaviour.

A real local PostgreSQL test verifies physical connection reuse and no prepared-statement accumulation over forty distinct statements. This does not establish production latency or explain the unidentified admin E2E failure; the failing URL/status/incident and deployed timing are still needed. The adaptation response now also fetches segment rows in one query rather than one per segment.

## 2. Osmosis guided questions

The audit found guidance on all five checkpoints, but none on the four assessment items. Four question-specific guidance sequences were added and passed the actual content-safety check. All nine stored questions now have guidance. Question IDs, answer keys and existing attempts were not rewritten. Future parse instructions request hints/guidance for assessments as well as checkpoints.

## 3. Cooldown and active help

AdaptResponse adds adjustmentDisposition (apply, retain, clear), cooldownUntil and supportGraceUntil. A cooldown is not a dismissal. Engine-issued unresolved help is retained in session delivery state and returned with the same decision ID, so a retained response is not a new offer. Solving the question or changing context clears it. A direct question hand-off can be retained without an engine-issued payload; clients must honour retain even when proactiveAdjustment is null.

The frontend must stop treating null alone as a command to dismiss. It should use adjustmentDisposition and avoid duplicate hint-offered events when the same decision is resent. Existing explicit child format/depth/Slower choices remain authoritative.

## 4. Narration

The real retry still returned YarnGPT 402 QUOTA_EXCEEDED on section 1. Further synthesis calls were stopped. Sections 1, 3, 4 and 5 remain ready for retry, not reported as recovered. After top-up, run:

`python scripts/repair_osmosis_guidance_audio.py --audio`

The script skips available recordings, uses the existing narration script, writes only successful results to Supabase-backed variants, and refuses to overwrite concurrent source edits.

## 5. Ended sittings

Online v1/content lesson reads and offline packages now hydrate choices/recommendations only from a sitting that is both in_progress and has no ended_at. Frozen configuration/session-state reads use the same active condition. Leaving a lesson therefore cannot leak its old first-section choice into a new sitting. The existing completed-review path remains separate and completion is not undone.

## 6. Guided-help grace

The backend now gates guided panels by the current question's consecutive miss run and its elapsed grace, not the miss count alone. The documented base windows are 45 seconds for Primary, 60 for JSS and 90 for SS; unknown age uses the conservative 90 seconds. No normalized attention value is fabricated to shorten that window. The device's separate productive-work inference remains on-device.

Attempt responses expose handoffAvailableAt once a three-miss run exists. The frontend must re-read attempts or call adapt when the deadline arrives, cancelling that scheduled read if the child solves the question or leaves. The server does not push a new panel merely because its clock passed a deadline. Adapt responses expose supportGraceUntil. The two-miss multi-signal policy was not relaxed while Lydia's ruling is pending.

## 7. Engagement decline

The recorded Osmosis indicators were task_switch, return_after_pause and navigation_fragmentation; there were no focus-duration readings. The prior duration calculation relied on focus_drop and therefore could not accumulate decline time from those interruption events.

Interrupted time can now be considered alongside navigation changes, never from a pause alone. Counts are normalized for observed duration. Sustained decline is measured against an observed personal baseline and resets across telemetry gaps. The HTTP regression proves that permitted stored events can produce engagement_decline. Missing baseline/evidence still means no inferred decline; no raw touch stream or visible state label was introduced.

## 8. Breaks and density

break_declined is now consumed and suppresses repeated offers for the existing 120-second cooldown, with suppressedReason and retryAt in breakSuggestion. A recorded break_start also suppresses fresh offers until break_end. This does not invent a timer duration.

Each segment adaptation carries densityScope=segment. Density applies only to that segment until a newer instruction for it replaces it; it must not spill into subsequent segments.

Open clarification: does "break window closes" mean expiry of an offer, or the end of an accepted timed break? Approved durations are required before adding authoritative expiry deadlines. A client needs a timer/deadline or polling/push to react without sending new interaction events; there is no existing unsolicited server push channel for this.

## Verification and remaining actions

364 parser, intelligence, consent, online/offline, grace, cooldown, real SQL pooling and engagement tests passed. Production re-run and the admin failure details remain outstanding. YarnGPT credits and the break-window duration ruling remain external dependencies. Frontend integration is required for the explicit retain/clear and grace-deadline contracts.
