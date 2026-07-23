# Microsoft 365 and Google Workspace SSO with roster sync

## Scope

Build SSO entry/callback handling, school URL generation, first-use routing,
and roster sync audit support for Microsoft 365 and Google Workspace.

## Acceptance criteria

1. Schools can be configured for Microsoft or Google SSO via
   `school_sso_configurations`.
2. `/api/v1/schools/{school_slug}/sso/{provider}/start` returns a provider
   authorization URL and `nevo.app/{school_slug}` entry URL.
3. `/api/v1/auth/sso/{provider}/callback` exchanges the provider callback,
   upserts the SSO user, issues a normal Nevo session, and returns first-use
   destination.
4. New students without a learner profile route to `observed_interaction`;
   returning students route to `home_dashboard`.
5. Roster sync records imported student/teacher counts and opens manual-review
   issues when teacher-class mappings are missing.
6. Roster sync is protected by the existing `it_sso` permission scope.

## Notes

Provider directory consent and token storage remain external provider concerns.
The backend has provider-client seams for Microsoft Graph and Google Workspace
Directory once tenant credentials are available.
