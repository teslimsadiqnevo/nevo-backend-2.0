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

The start script runs `alembic upgrade head` before Uvicorn, so migration
`0030` activates the durable post-lesson queue during deployment.
