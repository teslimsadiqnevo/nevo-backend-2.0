# ADR 0004: Scope-based staff permissions

- Status: Accepted for SCRUM-18
- Date: 2026-07-03
- Owners: Nevo backend team

## Context

Nevo staff accounts need flexible combinations of seven capabilities without
expanding the primary user-role enum for every job title. Permission changes
must take effect immediately, remain school-scoped, and retain a history of
grants and removals.

## Decision

- The exact scopes are `billing`, `roster`, `curriculum`, `senco`, `it_sso`,
  `oversight`, and `teacher`.
- `admins` is a one-to-one staff extension of `users`.
- `admin_scope_assignments` stores grants and soft revocations. A partial unique
  index permits one active row per admin and scope while preserving history.
- Teacher and SENCo roles retain their natural `teacher` and `senco` scopes.
  Additional scopes are explicit assignments.
- Permissions are loaded from PostgreSQL for each protected request rather than
  embedded in session tokens. Revocation is therefore immediate.
- All team-management queries are constrained to the authenticated user's
  school. An oversight administrator cannot remove their own oversight scope,
  and the repository serializes changes to prevent removal of the final active
  oversight administrator.
- Invitation tokens are opaque random values. Only an HMAC digest is stored.
  Invitations expire after seven days and are single-use.
- SSO-managed schools do not use the manual password invitation path; their
  staff lifecycle remains owned by the SSO/roster integration.

## Consequences

- Downstream endpoints can depend on one reusable `RequireScope` dependency.
- Frontends can render navigation from `/api/v1/permissions/me`.
- Scope history is auditable without a separate mutable JSON permissions field.
- School onboarding must create the first oversight assignment through a
  trusted provisioning path before team-management APIs can be used.
