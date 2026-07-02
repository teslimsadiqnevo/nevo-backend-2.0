# SCRUM-17: Auth service

## Acceptance criteria

1. Email/password login issues a revocable opaque session for active accounts.
2. PIN login requires school code, school-scoped login identifier, and PIN.
3. Passwords and PINs use Argon2id with separate server-side peppers.
4. Authentication respects the account and school auth methods from SCRUM-16.
5. Invited or deactivated accounts cannot authenticate.
6. Idle session timeouts are 60 minutes for students, 120 for teachers, 30 for
   SENCo admins, and 120 for other admins.
7. A second student login atomically revokes the prior active session.
8. A displaced session receives `session_replaced` and the required user-facing
   message on its next authenticated request.
9. Login attempts are rate-limited without storing raw email, login identifier,
   school code, or IP address in the limiter.
10. Security-relevant auth events are auditable.
11. Tests cover successful and failed credential flows, account status, timeout
    policy, expiry, logout, rate limiting, and concurrent student login.

## SCRUM-16 integration contract

SCRUM-17 consumes `users.id`, `users.school_id`, `users.role`,
`users.auth_method`, `users.email`, `users.password_hash`, `users.pin_hash`,
`users.status`, `users.deactivated_at`, plus `schools.school_code` and
`schools.auth_method`.

SCRUM-17 adds nullable `users.login_identifier`, constrained unique by
`(school_id, login_identifier)`, for PIN-authenticated learners.
