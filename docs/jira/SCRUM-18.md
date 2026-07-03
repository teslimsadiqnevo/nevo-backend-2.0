# SCRUM-18: Role-based permission system

## Acceptance criteria

1. The permission vocabulary contains exactly `billing`, `roster`,
   `curriculum`, `senco`, `it_sso`, `oversight`, and `teacher`.
2. A staff user can hold multiple active scopes.
3. Scope edits preserve revoked assignment history and take effect on the next
   protected request.
4. Teacher and SENCo roles receive their natural base scope.
5. Permission and team queries cannot cross school boundaries.
6. Only an oversight-scoped user can list the admin team, invite staff, or edit
   scopes.
7. A school cannot lose its final active oversight administrator.
8. Manual invitations are normalized, expire after seven days, are single-use,
   store only a token digest, and activate the invited account after password
   setup.
9. SSO-managed schools reject the manual invitation path.
10. `/api/v1/permissions/me` returns effective scopes and deterministic
    navigation destinations.
11. Tests cover policy, APIs, schema, migration rendering, invitation
    acceptance, scope history, and final-oversight protection.

## API surface

- `GET /api/v1/permissions/me`
- `GET /api/v1/admin/team`
- `POST /api/v1/admin/team/invitations`
- `POST /api/v1/admin/team/invitations/accept`
- `PUT /api/v1/admin/team/{user_id}/scopes`

## Dependency

SCRUM-18 builds on the account schema from SCRUM-16 and authenticated principals
from SCRUM-17.
