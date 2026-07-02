# ADR 0003: Authentication and session service

- Status: Accepted for SCRUM-17
- Date: 2026-07-02
- Owners: Nevo backend team

## Context

Nevo needs manual email/password login, younger-student PIN login, immediate
session revocation, role-based timeouts, and single-session enforcement for
students. Those requirements make stateless bearer JWTs a poor primary session
mechanism because a displaced student session must stop working immediately.

## Decision

### Credentials

- Passwords and PINs use Argon2id with independent server-side peppers.
- Raw credentials are never persisted or logged.
- PIN login requires `school_code + login_identifier + PIN`; a PIN alone is not
  an identity.
- `login_identifier` is unique within a school and is owned by the auth schema.
- Authentication errors do not reveal whether an account exists.

### Sessions

- Access tokens are opaque 256-bit random values returned once at login.
- Only an HMAC-SHA256 token digest is stored.
- Sessions are revocable database records with a role snapshot, last-seen time,
  expiry, revocation reason, and replacement link.
- Role timeouts are sliding idle windows:
  - student: 60 minutes
  - teacher: 120 minutes
  - SENCo admin: 30 minutes
  - other admin: 120 minutes
- A student login atomically revokes any prior active student session.
- A replaced token receives the stable error code `session_replaced` and the
  product message required by SCRUM-17 on its next request.

### Abuse controls

- Failed login attempts are rate-limited by HMAC-hashed account identifier and
  IP address.
- Login success/failure, revocation, expiry, and replacement are audit events.
- Deactivated and invited accounts cannot receive sessions.

## Consequences

- Each authenticated request performs a session lookup, enabling immediate
  revocation and accurate concurrent-session behavior.
- A later cache may accelerate valid-session reads, but the database remains the
  source of truth.
- SCRUM-16 must exist before the auth persistence migration can run.
- SSO token exchange remains a separate provider integration; its resulting
  Nevo session will use this same session service.
