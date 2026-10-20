# Signal-path wording: backend response

Update: the pending-consent policy described in point 3 below was subsequently
superseded by SCRUM-257. Confirmed consent is now required; see
`docs/jira/SCRUM-257.md` and the twelve-item reply of 20 October. The rest of this
document remains the dated signal-path response.

20 October 2026. Response to `Nevo_Signals_Wording_19Oct.md`.

This is the signal-path wording review, not a replacement for the twelve-item engine work list. The source document reports frontend behaviour at commit `12f103e`; that browser build has not been independently verified in this backend task. No frontend code was changed.

## Backend findings and corrections

1. **Server inference and persistent evidence: confirmed.** Permitted lesson events, submitted answers, progress and relevant history reach the API and are written to PostgreSQL. Backend inference is not an end-of-session memory-only process. There is no secure-memory-wipe or fixed memory-residency guarantee.
2. **Retention placeholder: resolved for covered application records.** Migration `20261020_0110` has been applied and read back from the configured database. Signal events and profile history now participate in the purge, rather than merely losing account names. The default deadline is 180 days after recorded purpose cessation, or earlier under a shorter school window. Deactivation, explicit withdrawal of processing consent and the SENCo end-purpose route start that clock. An hourly worker performs deletion with retry/audit records. No learners were overdue in the migration verification query. This is not a production purge-run certificate or a guarantee about backups, hosting logs, vendor copies or downloaded files; see `docs/content-safety-and-retention.md`.
3. **Missing consent service: fixed server-side.** `/api/signals/` now refuses collection with `503 consent_service_unavailable` if the gate is missing or fails. Explicit withdrawal gives `403 consent_withdrawn`; neither path calls ingestion. This prevents a fail-open browser from overriding the server. Existing policy still permits a pending/missing consent record and blocks explicit withdrawal; it must not be described as requiring affirmative recorded consent before every use. Changing that policy requires an explicit product/counsel decision.
4. **Raw-input rejection: hardened.** Forbidden input fields are checked recursively, including arrays and legacy top-level event fields merged into `eventData`. Nested coordinates, pressure and raw-input measurements can no longer bypass the old top-level check. The baseline aggregate endpoint uses the same recursive guard. This is a rejection rule, not proof that a browser never attempted transmission.
5. **Crash reporting: minimised.** The application logger no longer records the browser's free-text message, stack, literal route, version text or signed-in account ID. It records a server-validated incident reference, surface, a closed error-kind value, route/build fingerprints and whether a stack was supplied. The incoming HTTP request still reaches the server; no claim is made about external proxy/error instrumentation or deletion of older logs. Frontend prevention of sensitive crash payloads remains necessary.

## Wording that still needs correction

- **"No third party receives it" is too broad.** Requests go to Nevo's authenticated API, but the backend uses contracted hosting/database/storage processors. Educational AI requests and permitted pseudonymised context can also pass through the AI Gateway to the model provider. Do not turn "no direct browser analytics recipient" into "no processor ever handles data".
- **"Calculation entries are not sent" cannot describe the backend contract.** The answer endpoint accepts `source: "calculation"` with an `answer`, marks it on the server, and stores the attempt. If a particular frontend build omits this call, that is a dated frontend observation, not a backend privacy guarantee. The notice must include deliberately submitted learning answers, not only messages and Ask Nevo questions.
- **"All derived outputs are withheld from the school and learner" is too broad.** Internal cognitive measurements are not intended as visible scores, but the client receives delivery configuration/actions and authorised staff receive functional insights, flags, recommendations and support history. "Not presented as cognitive scores" is different from "not transmitted or accessible in any response".
- **"The device computes no score" conflicts with the same document's local answer marking.** Say that the backend computes the learner model and adaptation decisions. Local activity marking and deterministic rendering are a separate matter, for frontend confirmation.
- **"Nobody at school is shown what Nevo works out" is not true as an absolute.** Authorised school staff see functional progress and support information. They must not be promised that no inferred information is ever available to them.
- **Training influence:** do not imply that a deployed trained AKT model exists today. The current supported mastery path is local rule-based/BKT; the proposed AKT training/deployment remains separate. Provider-training/retention claims require the actual provider agreement, not an assumption from account deletion.

## Suggested technical replacement

> The learner's device sends permitted learning events and deliberately submitted answers to Nevo's authenticated backend over an encrypted connection. These can include lesson and segment identifiers, timestamps, durations, reading progress, replay and hint actions, breaks, format changes, submitted answers and progress. The backend computes the learner model and adaptation decisions from this evidence and relevant history. The client receives the instructions and delivery settings needed to present the lesson.
>
> Accepted learning events and answer records are stored in the database; they are not held only in memory or deleted at the end of a lesson. Covered application records are scheduled for deletion 180 days after the recorded processing purpose ends, or sooner under a shorter school policy. Retention of backups, infrastructure logs, processor copies and downloaded material is governed separately and must be verified separately.
>
> The backend rejects prohibited raw-input measurements rather than treating them as learning events. Claims about whether coordinates are captured locally, whether local activity marking occurs, or when browser storage is cleared must be confirmed against the released frontend. Authorised school staff can see functional progress and support information, not diagnostic labels or cognitive scores presented as assessments.

## Suggested parent-facing replacement

> Nevo receives a record of how your child works through a lesson, including the answers they choose or submit, time spent on parts of the lesson, reading progress, replays, hints and breaks. Nevo uses this record on its servers to adjust how lessons are presented. The lesson record is stored so progress can be followed over time; it is not deleted when a lesson ends.
>
> Covered learning records are scheduled for deletion within 180 days after Nevo records that the purpose for processing has ended, or sooner where the school's policy requires it. Authorised school staff can see functional information about progress and support. Nevo uses service providers to host and operate the platform and an AI provider for supported educational features; the privacy notice must identify these arrangements accurately.

This paragraph does not replace the separately verified frontend description of local touch capture or the full processor/retention schedule.

## Suggested child-facing replacement

> Nevo keeps a record of the answers you submit and how you use a lesson, such as when you replay something, use a hint or take a break. Nevo uses this to help choose how to show the lesson. People at your school who are allowed to help you can see information about your progress and support.

Add any sentence about where a finger lands or local storage only after frontend confirmation; do not infer it from the backend rejection rule.

## Frontend-owned checks still open

- Confirm the current release captures no lesson touch coordinates and does not transmit raw onboarding coordinates.
- Confirm what local activity marking and deterministic rules compute; avoid the absolute "no score" wording without that check.
- Verify purge after abandoned onboarding, sign-out, account switching and expiry on a shared device. The server cannot erase that browser storage.
- Change the browser's consent-check failure default to deny/pause collection, and verify its retry behaviour. The backend now fails closed independently.
- Check the current calculation submission, Socratic text and crash-report payloads, rather than relying on the older build observation.

The six legal documents were not supplied in this task and have not been edited. These are engineering corrections for Lydia/counsel to apply, not a declaration that the legal pack or frontend has been verified.
