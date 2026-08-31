# Deployment environment

The production AI runtime is Claude only. Gemini variables are ignored and
should be removed from Render.

## Required

- `DATABASE_URL`: Supabase PostgreSQL pooler URL. Use the async-compatible
  PostgreSQL URL accepted by the application; TLS is enabled for Supabase.
- `AUTH_PASSWORD_PEPPER`, `AUTH_PIN_PEPPER`, `AUTH_SESSION_PEPPER`: three
  independent high-entropy secrets.
- `AI_PROVIDER=claude`.
- `AI_ANTHROPIC_API_KEY`: Anthropic production API key.
- `CONSENT_PUBLIC_BASE_URL`: public frontend origin.

## Claude routing

- `AI_ANTHROPIC_MODEL=claude-haiku-4-5`.
- `AI_ANTHROPIC_SONNET_MODEL=claude-sonnet`.
- `AI_PROMPT_CACHING_ENABLED=true`.
- `AI_REQUESTS_PER_MINUTE=60`.
- `AI_MAX_CONCURRENCY=4`.

## SSO and roster sync

- `SSO_PUBLIC_BASE_URL`: public backend origin, for example
  `https://api.nevolearning.com`.
- `SSO_SCHOOL_BASE_URL`: public school-entry frontend origin.
- `SSO_MICROSOFT_CLIENT_SECRET`: Microsoft Entra application secret. The app
  also needs Microsoft Graph Education roster application permissions with
  administrator consent. Grant delegated `EduRoster.ReadBasic` and `User.Read`,
  plus application `EduRoster.Read.All` and `Files.Read.All`.
- `SSO_GOOGLE_CLIENT_SECRET`: Google OAuth client secret.
- `SSO_GOOGLE_REFRESH_TOKEN`: refresh token granted with Google Classroom
  course and roster read-only scopes. This is a bootstrap fallback; successful
  reauthorisation stores the replacement encrypted per school.
- Google consent must include Classroom courses, rosters and profile email
  read-only scopes plus Drive read-only access.
- `SSO_CREDENTIAL_ENCRYPTION_KEY`: a Fernet key used to encrypt provider
  refresh tokens before database storage. Generate with
  `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.

Each school's provider client ID, Microsoft tenant ID or Google hosted domain,
and school slug remain in `school_sso_configurations`.

## Transactional email

- `RESEND_API_KEY`: production Resend API key.
- `RESEND_FROM_ADDRESS`: optional verified sender; defaults to
  `Nevo <noreply@nevolearning.com>`.
- `EMAIL_FRONTEND_BASE_URL`: used in invitation and password-reset links.

## Parent consent delivery

The consent outbox worker delivers parent consent requests. Email needs nothing
beyond `RESEND_API_KEY`. SMS is optional:

- `TERMII_API_KEY`: optional. Without it, consent requests addressed to a phone
  number stay queued and retry rather than being lost.
- `TERMII_SENDER_ID=Nevo`: approved Termii sender ID.

## Payments

Dropping in the secret key switches on checkout, webhook reconciliation, saved
card charging, invoice issuance, and daily collection.

- `PAYSTACK_SECRET_KEY`: production secret key. Also used to verify webhook
  signatures, so it must be the key belonging to the same Paystack account that
  sends the callbacks.
- `PAYSTACK_CALLBACK_URL`: where Paystack returns the payer after checkout.
- `PAYSTACK_CURRENCY=NGN`: currency invoices are charged in.
- `PAYSTACK_AUTO_CHARGE_ENABLED=true`: allows the daily job to charge a stored
  authorization for a due invoice.

In the Paystack dashboard, set the webhook URL to
`POST {backend}/api/billing/payments/webhook`. The endpoint is unauthenticated
by design — trust comes from the HMAC-SHA512 signature over the raw body. Every
event is de-duplicated, and the transaction amount is re-fetched from the
Paystack API before an invoice is marked paid, so a forged or replayed callback
cannot clear an invoice.

## Lesson imagery

- `OPENAI_API_KEY`: required for generated lesson visuals.
- `IMAGE_GENERATION_MODEL=gpt-image-2`, `IMAGE_GENERATION_QUALITY=high`,
  `IMAGE_GENERATION_SIZE=1536x1024`.
- `IMAGE_VALIDATOR_MODEL=claude-opus-4-8`: the Claude vision model that reviews
  each candidate against the lesson text before it is stored.
- `IMAGE_GENERATION_MAX_ATTEMPTS=3`: regeneration attempts before the segment is
  flagged for human review instead of shipping a bad image.

Reviewed images are stored in the same bucket as audio, under
`images/lessons/`, keyed by a digest of the prompt.

## Lesson audio and storage

- `YARNGPT_API_KEY`: production YarnGPT API key.
- `YARNGPT_API_URL=https://yarngpt.ai/api/v1/tts`.
- `YARNGPT_VOICE=Idera`: voice sent to YarnGPT.
- `SUPABASE_URL`: project API URL, for example
  `https://your-project.supabase.co`. This is not the PostgreSQL connection URL.
- `SUPABASE_SERVICE_ROLE_KEY`: server-only service-role key used to inspect and
  upload objects. Never expose this value to the frontend.
- `SUPABASE_STORAGE_BUCKET=lesson-media`.
- `SUPABASE_STORAGE_PUBLIC`: `true` for a public bucket, whose media URLs are
  stable and never expire. Set `false` for a private bucket — media URLs then
  become short-lived signed URLs, and no service credential ever reaches the
  client either way.
- `SUPABASE_SIGNED_URL_TTL_SECONDS=604800`: signed URL lifetime for a private
  bucket. Seven days is the Supabase maximum; longer values are clamped.

Audio is generated during lesson parsing, stored as MP3, and keyed by a digest
of the voice and normalized script. Re-parsing identical narration reuses the
existing object instead of paying for another generation.

On a private bucket, a stored URL eventually expires. The frontend refreshes one
by posting the segment's `storagePath` to `POST /api/content/media/url`, which
returns a fresh URL and its `expiresInSeconds`. Only paths under `audio/` and
`images/` can be signed.

## Background jobs

Six recurring jobs run under the scheduled job runner inside the web process:
`retention.anonymise`, `scheduler.refresh_due_dates`, `sso.roster_sync`,
`sso.health_probe`, `billing.issue_invoices`, and
`billing.collect_due_invoices`. Each takes a Postgres advisory lock, so running
several web instances does not double-execute a job. Outcomes are recorded in
`scheduled_job_runs` — query that table for the last status and summary of each
job. See [WORKER_TOPOLOGY.md](WORKER_TOPOLOGY.md) for the scaling
recommendation and the alerting that is still worth adding.

## Commands

Build: `bash scripts/render-build.sh`

Start: `bash scripts/render-start.sh`

Seed the three connected demo roles after migrations:

```bash
NEVO_DEMO_TEACHER_PASSWORD='...' \
NEVO_DEMO_ADMIN_PASSWORD='...' \
NEVO_DEMO_STUDENT_PASSWORD='...' \
NEVO_DEMO_STUDENT_PIN='...' \
python scripts/seed_demo_teacher_console.py
```

This creates or refreshes `teacher.demo@nevolearning.com`,
`admin.demo@nevolearning.com`, and `student.demo@nevolearning.com` in Nevo Demo
School. Passwords and PINs are always hashed with the currently configured
deployment peppers.

The start script runs `alembic upgrade head` before Uvicorn. Head is
`20260831_0033`, which adds the consent delivery retry columns (`0031`), the
Paystack transaction and webhook tables (`0032`), and the scheduled job run
table plus the `users.anonymised_at` retention marker (`0033`).
