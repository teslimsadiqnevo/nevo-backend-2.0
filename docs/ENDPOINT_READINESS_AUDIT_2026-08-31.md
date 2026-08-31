# Endpoint readiness audit - 2026-08-31

## Scope

The application currently registers 170 HTTP operations across 20 Swagger
groups. Every JSON operation has a named response model, and no route returns a
deliberate `501` or `NotImplemented` placeholder. That means the API contract is
integrable; it does not mean every external or scheduled workflow is production
operational.

## Status by API group

| API group | Operations | Readiness | What full use requires |
| --- | ---: | --- | --- |
| System | 1 | Ready | Database connectivity for the full health result. |
| Authentication | 8 | Ready with setup | Peppers, migrated database, seeded/created users. Password-reset delivery needs Resend. |
| Product access | 17 | Ready with setup | Resend for invitations and resets. Parent-right links must be delivered by the caller because consent delivery has no worker. |
| School administration | 34 | Ready | Correct school membership and role/scope data. Anonymisation is manual, not retention-driven. |
| Teacher assignments | 7 | Ready | Teacher, class, and roster records in the same tenant. |
| Learning product | 23 | Mostly ready | Claude for parsing, YarnGPT/Supabase for audio, SSO credentials for cloud imports. Generated visual images remain incomplete. |
| Content | 6 | Mostly ready | Same parsing dependencies as learning product. Direct audio playback requires the configured public bucket. |
| Signals | 1 | Ready | Valid consent, lesson session, and migrated signal enums/tables. Post-lesson work runs through the database-backed worker. |
| Intelligence | 19 | Ready from available data | Useful output requires sufficient sessions/signals. Claude is needed for model-written recommendations; local inference routes do not need Claude. |
| Mastery | 4 | Ready | Concepts and student attempts must exist. The engine itself is local. |
| Scheduler | 3 | API ready, automation incomplete | Review recording and due reads work. Daily `refresh-due-dates` is not scheduled automatically. |
| Ask Nevo | 2 | Ready with setup | Claude key and prompt migrations. The privacy guard removes structured identifiers and common labelled identifiers, but cannot guarantee recognition of every unlabelled personal name in free prose. |
| AI gateway | 1 | Ready with setup | Claude key and prompt template. This generic route should remain tightly scoped because it is a broad model entry point. |
| Exports | 5 | Ready with setup | Claude for draft generation and a real parent account/link for sharing. SENCo finalisation rules are enforced. |
| SSO | 10 | API ready, automation incomplete | Provider app credentials, encrypted per-school configuration, consented scopes, tenant/domain, and school slug. No scheduled roster-sync runner or periodic health probe exists. |
| Notifications | 3 | Ready | In-app notifications work. Email delivery needs Resend and the process-local delivery worker running. |
| Messaging | 3 | Ready | Valid authorised thread participants. No external push/mobile transport exists. |
| Billing | 6 | Partially operational | Reads, contact storage, masked method metadata, and generated invoice PDFs work. There is no Paystack/processor tokenisation, charge collection, webhook reconciliation, or invoice-issuance job. |
| Admin | 6 | Ready within backend scope | Compliance scan/PDF and adaptation logs work against backend records. They cannot prove claims about data that a frontend may retain or transmit. |
| Permissions | 5 | Ready with setup | Resend for emailed team invitations; permission scopes and school context must be seeded. |
| Partner inquiries | 1 | Ready | Database only; no CRM forwarding or notification workflow exists. |

## Genuine code gaps

These are not solved by adding environment variables.

1. **Generated lesson images:** Claude returns text, not stored image assets.
   The parser rejects incomplete image objects and marks them for review, but no
   image provider currently creates and uploads a valid visual variant.
2. **Billing processor:** payment-method updates persist masked metadata and a
   caller-supplied processor reference. The backend does not create or verify a
   Paystack/direct-debit method, collect charges, consume webhooks, or issue
   invoices automatically.
3. **Automatic retention:** schools have retention settings and admins can
   manually anonymise a student, but there is no scheduled enrolment-plus-12-
   month anonymisation/purge worker.
4. **Parent consent delivery:** consent requests create a durable outbox entry
   and URL, but no email/SMS worker currently consumes that consent outbox.
5. **Scheduled jobs:** FSRS due-date refresh and roster sync are request-driven.
   Neither has a daily scheduler; SSO health changes only after a provider call.
6. **Private audio playback:** YarnGPT generation and Supabase upload are now
   implemented. The current returned URL is directly playable only when the
   bucket is public. Private delivery needs short-lived signed URLs or an
   authenticated streaming design agreed with the frontend.
7. **Unstructured-name redaction:** all AI calls pass through one server-side
   privacy guard. It strips structured identity fields, emails, phone numbers,
   credentials, and labelled names. An arbitrary unlabelled name embedded in a
   natural-language question cannot be guaranteed to be detected by regex, so
   compliance wording must not claim perfect de-identification of all prose.
8. **Worker topology:** notification email and post-lesson processing use
   durable database state, but consumers run inside each web process. This is
   functional on the current single-instance deployment; a multi-instance
   rollout should move consumers to dedicated workers or add explicit claiming
   locks and operational supervision.

## Deployment-only blockers

Full use of the implemented integrations requires:

- `AI_ANTHROPIC_API_KEY` and the Claude routing variables.
- `RESEND_API_KEY`, a verified `RESEND_FROM_ADDRESS`, and the frontend URL.
- `YARNGPT_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, the
  `lesson-media` bucket, and its public-read setting for current playback.
- Microsoft Entra and Google OAuth credentials/scopes plus per-school SSO rows.
- Current database migrations, production auth peppers, frontend/consent public
  URLs, seeded permission scopes, school membership, and realistic test data.

## Bottom line

The CRUD, authentication, lesson/session, signals, local intelligence, mastery,
messaging, admin audit, and reporting contracts are usable. The product is not
honestly "fully operational across all 170 operations" until the eight code
gaps above are either implemented or explicitly removed from the launch scope.
