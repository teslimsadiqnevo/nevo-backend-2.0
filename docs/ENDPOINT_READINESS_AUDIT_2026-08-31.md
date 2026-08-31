# Endpoint readiness audit - 2026-08-31

## Scope

The application currently registers 174 HTTP operations across 20 Swagger
groups. Every JSON operation has a named response model, and no route returns a
deliberate `501` or `NotImplemented` placeholder. That means the API contract is
integrable; it does not mean every external or scheduled workflow is production
operational.

## Status by API group

| API group | Operations | Readiness | What full use requires |
| --- | ---: | --- | --- |
| System | 1 | Ready | Database connectivity for the full health result. |
| Authentication | 8 | Ready with setup | Peppers, migrated database, seeded/created users. Password-reset delivery needs Resend. |
| Product access | 17 | Ready with setup | Resend for invitations and resets. Parent consent links are delivered by the consent outbox worker (Resend, or Termii for SMS). |
| School administration | 34 | Ready | Correct school membership and role/scope data. Anonymisation is both manual and retention-driven via the daily sweep. |
| Teacher assignments | 7 | Ready | Teacher, class, and roster records in the same tenant. |
| Learning product | 23 | Ready with setup | Claude for parsing, YarnGPT/Supabase for audio, SSO credentials for cloud imports, and OpenAI for reviewed visual images. |
| Content | 7 | Ready with setup | Same parsing dependencies as learning product. Public and private buckets both play back; private buckets use signed URLs refreshed via `POST /api/content/media/url`. |
| Signals | 1 | Ready | Valid consent, lesson session, and migrated signal enums/tables. Post-lesson work runs through the database-backed worker. |
| Intelligence | 19 | Ready from available data | Useful output requires sufficient sessions/signals. Claude is needed for model-written recommendations; local inference routes do not need Claude. |
| Mastery | 4 | Ready | Concepts and student attempts must exist. The engine itself is local. |
| Scheduler | 3 | Ready | Review recording and due reads work. `scheduler.refresh_due_dates` runs daily under the scheduled job runner. |
| Ask Nevo | 2 | Ready with setup | Claude key and prompt migrations. The privacy guard removes structured identifiers, labelled identifiers, and the known names of the requester, student, and their parents; an unrelated third party's name in free prose is still not guaranteed to be caught. |
| AI gateway | 1 | Ready with setup | Claude key and prompt template. This generic route should remain tightly scoped because it is a broad model entry point. |
| Exports | 5 | Ready with setup | Claude for draft generation and a real parent account/link for sharing. SENCo finalisation rules are enforced. |
| SSO | 10 | Ready with setup | Provider app credentials, encrypted per-school configuration, consented scopes, tenant/domain, and school slug. Roster sync runs daily and the health probe hourly. |
| Notifications | 3 | Ready | In-app notifications work. Email delivery needs Resend and the process-local delivery worker running. |
| Messaging | 3 | Ready | Valid authorised thread participants. No external push/mobile transport exists. |
| Billing | 9 | Ready with setup | Needs `PAYSTACK_SECRET_KEY` and a dashboard webhook. Checkout, verification, signed webhook reconciliation, saved-card charging, daily invoice issuance, and daily collection all operate. |
| Admin | 6 | Ready within backend scope | Compliance scan/PDF and adaptation logs work against backend records. They cannot prove claims about data that a frontend may retain or transmit. |
| Permissions | 5 | Ready with setup | Resend for emailed team invitations; permission scopes and school context must be seeded. |
| Partner inquiries | 1 | Ready | Database only; no CRM forwarding or notification workflow exists. |

## Code gaps — resolved 2026-08-31

The eight gaps below were the blocking list. Seven are now implemented; the
eighth was a topology question and has been answered.

1. **Generated lesson images — implemented.** `nevo.visuals` generates the
   asset with GPT Image 2, then passes it to Claude vision for an educational
   review against the lesson text (factual accuracy, numeric exactness,
   labelling, readability, age-appropriateness). A rejected image is
   regenerated with the reviewer's correction appended, up to
   `IMAGE_GENERATION_MAX_ATTEMPTS`; an image that never passes is never
   uploaded and the segment is flagged for review. Requires `OPENAI_API_KEY`
   in addition to the existing Claude key.
2. **Billing processor — implemented.** `nevo.payments` covers hosted checkout
   (`POST /api/billing/payments/checkout`), verification
   (`POST /api/billing/payments/{reference}/verify`), signed webhook receipt
   (`POST /api/billing/payments/webhook`), and charging a stored authorization.
   Two safety rules are enforced: the webhook body is never trusted — the
   amount is re-fetched from the Paystack API before value is granted — and a
   transaction that already succeeded can never be settled twice. Invoices are
   raised by `billing.issue_invoices` and collected by
   `billing.collect_due_invoices`. Only `PAYSTACK_SECRET_KEY` is required.
3. **Automatic retention — implemented.** The daily `retention.anonymise` job
   anonymises any student whose deactivation is older than their school's
   `data_retention_days`. The SENCo's manual delete and the scheduled sweep now
   call the same routine, so both produce an identical result, and
   `users.anonymised_at` makes the sweep idempotent.
4. **Parent consent delivery — implemented.** `ConsentDeliveryWorker` consumes
   the consent outbox with Resend for email and Termii for SMS, with attempt
   counting and exponential backoff. SMS is optional; an unconfigured transport
   leaves the request queued rather than losing it.
5. **Scheduled jobs — implemented.** `ScheduledJobRunner` runs
   `retention.anonymise`, `scheduler.refresh_due_dates`, `sso.roster_sync`,
   `sso.health_probe`, `billing.issue_invoices`, and
   `billing.collect_due_invoices`, recording each outcome in
   `scheduled_job_runs`.
6. **Private media playback — implemented.** `nevo.storage` returns a public
   URL for a public bucket and a short-lived signed URL for a private one.
   `POST /api/content/media/url` re-issues an expired URL, so a lesson parsed
   months ago stays playable. Applies to both audio and generated imagery.
7. **Unstructured-name redaction — improved, with a caveat that stands.** The
   guard now also strikes out the known names of the people a prompt can be
   about — the requester, the student, and that student's parents — by exact
   match, alongside the structured and labelled-identifier patterns. A
   correctness bug was fixed in the process: the labelled-identifier pattern was
   greedy past a full stop and had been deleting the remainder of the lesson
   text after a name. The honest limit is unchanged: an unrelated third party's
   name in free prose (a name belonging to nobody on the roster) still cannot
   be guaranteed to be detected, so compliance wording must not claim perfect
   de-identification of arbitrary prose.
8. **Worker topology — answered, no code change required.** All five
   background consumers already claim work through Postgres row locks
   (`SELECT ... FOR UPDATE SKIP LOCKED`) or per-job advisory locks, so running
   them on multiple web instances is safe today. The recommendation — split the
   scheduler into its own process, then add queue-depth and job-staleness
   alerting, and do not introduce a broker yet — is in
   [WORKER_TOPOLOGY.md](WORKER_TOPOLOGY.md).

## Deployment-only blockers

Full use of the implemented integrations requires:

- `AI_ANTHROPIC_API_KEY` and the Claude routing variables.
- `OPENAI_API_KEY` for lesson image generation.
- `PAYSTACK_SECRET_KEY`, plus a dashboard webhook pointed at
  `POST {backend}/api/billing/payments/webhook`.
- `RESEND_API_KEY`, a verified `RESEND_FROM_ADDRESS`, and the frontend URL.
  `TERMII_API_KEY` is optional and only needed for SMS consent requests.
- `YARNGPT_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, and the
  `lesson-media` bucket. A private bucket is now supported via signed URLs.
- Microsoft Entra and Google OAuth credentials/scopes plus per-school SSO rows.
- Current database migrations (head is `20260831_0033`), production auth
  peppers, frontend/consent public URLs, seeded permission scopes, school
  membership, and realistic test data.

## Remaining honest caveats

Not blockers, but they should not be overclaimed:

- **Redaction of arbitrary prose.** See gap 7 above. Names of people unknown to
  the roster are not guaranteed to be stripped from free text.
- **Image review is a model judgement.** The Claude vision gate rejects images
  that are factually wrong, mislabelled, or unreadable, and refuses to ship one
  that never passes. It is a strong filter, not a proof of correctness.
- **Invoice issuance assumes a 365-day contract year** and prices from the
  contract's `current_year_index`; advancing that index at renewal is still an
  administrative action.
- **Operational alerting does not exist yet.** Queue depth and job staleness are
  both queryable but nothing pages anyone — see
  [WORKER_TOPOLOGY.md](WORKER_TOPOLOGY.md) step 3.

## Bottom line

The CRUD, authentication, lesson/session, signals, local intelligence, mastery,
messaging, admin audit, and reporting contracts are usable. The eight code gaps
that previously blocked an honest "fully operational" claim are now closed: the
remaining work to go live is configuration, the operational alerting described
in the worker topology note, and verification against a real database.
