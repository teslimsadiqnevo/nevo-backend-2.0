# Admin dashboard: IT/SSO configuration and roster sync management

Backend contract. Split off from SCRUM-41; SCRUM-39 covers first-time setup
and SCRUM-28 built the underlying SSO and roster sync. This ticket adds the
ongoing management surface on top.

## Endpoints

All five require the `it_sso` permission scope and act on the actor's own
school, taken from the permission snapshot rather than a path parameter. A
school with no configuration returns `404 sso_not_configured`; an actor with
no school context returns `403 missing_school_context`.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/v1/admin/sso/status` | Connection health and data flow notice |
| `GET` | `/api/v1/admin/sso/roster-sync-history` | Sync history and failed events |
| `POST` | `/api/v1/admin/sso/roster-sync` | Manual sync outside the schedule |
| `POST` | `/api/v1/admin/sso/reauthorise` | Fresh provider authorisation URL |
| `POST` | `/api/v1/admin/sso/disconnect` | Soft disable, keeping all accounts |

### Status

Returns provider, `connection_status`, last successful sync, next scheduled
sync, the school entry URL, and the plain-language data flow notice.

The endpoint **reports** rather than probes. Calling the identity provider on
every dashboard render would put a third-party round trip on a page load.
Status is written when a real provider interaction succeeds or fails.

`data_flow` is served from the backend (`SSO_DATA_FLOW`) rather than written
into the frontend, so the transparency notice cannot drift from the code that
actually reads the directory.

### Health transitions

- A roster sync that reaches the provider clears `needs_attention` back to
  `connected` on its own. The admin never has to dismiss a resolved warning.
- A provider refusal during a manual sync writes `needs_attention` with the
  reason, and records a failed run rather than letting the error vanish.
- A deliberate `disconnected` state is never overwritten by either path.

### Sync history

`window_days` defaults to 30 and is bounded to 1..365 (`422` outside that).
Returns successful and failed run counts plus each run, with failed events
carrying `failure_reason`, and each issue carrying a `resolution_hint`
naming the action the administrator can take.

### Disconnect

`{"confirm": true}` is required; `false` returns `400 confirmation_required`.
This is the second of two confirmations, the first being in the dashboard.

Disconnecting is a soft disable: `enabled` goes false, `connection_status`
becomes `disconnected`, and the scheduled sync is cleared. **No account is
deactivated or deleted, and no data is removed.** The response returns
`retained_user_count` so the confirmation screen can state the real number
instead of a vague reassurance.

While disconnected, a manual roster sync returns `409 sso_disconnected`
rather than quietly pulling the directory anyway: the disconnect was
deliberate, and reauthorise is the way back. A successful sync also cannot
clear a `disconnected` state, only a `needs_attention` one.

## Schema

`school_sso_configurations` gains `connection_status`,
`last_connection_error`, `connection_checked_at`, `reauthorised_at`,
`next_scheduled_sync_at`, `disconnected_at`, and `disconnected_by_user_id`,
with a check tying `disconnected` to its timestamp. The user foreign key is
`ON DELETE SET NULL` so audit state can never cascade into an account.

`roster_sync_runs` gains `failure_reason`, `triggered_manually`, and
`triggered_by_user_id`. `roster_sync_issues` gains `resolution_hint`.

Migration `20260812_0019` backfills any configuration already disabled to
`disconnected`, since that was previously the only way to turn one off.

## Definition of done

Backend items only; design and dashboard work are tracked on the parent.

- [x] Admin can read SSO status and health.
- [x] Admin can reauthorise when credentials lapse.
- [x] Admin can trigger a manual roster sync.
- [x] Admin can read sync history with failed events explained.
- [x] Admin can disconnect with accounts retained.
- [x] Copy in Nevo voice, no jargon (asserted in tests).

## Notes

`next_scheduled_sync_at` is stored and served but nothing writes it yet: there
is no roster sync scheduler in the backend, and the existing sync is
request-driven. The dashboard should treat a null as "no sync scheduled"
rather than rendering an empty slot. A scheduler is a separate ticket.

Provider credential expiry is only observed when a sync is attempted. Until a
scheduler exists, a school whose permission lapsed shows `connected` until
someone presses sync.
