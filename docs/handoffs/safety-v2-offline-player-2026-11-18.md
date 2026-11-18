# Safety v2 offline player contract for Yinka

The backend changes are on `main`. The policy flag remains off.

## Download and open

- `POST /api/v1/lessons/{lessonId}/download` returns a download `id` and a
  manifest with `generatedAt` and `expiresAt`. Save the download id with the
  cached package.
- `lesson.json` in a newly fetched package also carries `generatedAt` and
  `expiresAt`. Never open it offline after `expiresAt`; ask the child to
  connect once to refresh it. A legacy package with no expiry needs a fresh
  download before the fourteen-day rule can be enforced.
- On the **first connection**, before rendering or reading any cached lesson
  content, call `GET /api/v1/offline-downloads/{downloadId}/status`.
  `usable: false` with `reason: safety_revoked` means delete the cached
  package before opening it. `expired` means refresh it. `current` allows
  normal use. A failed status request must not be interpreted as `current`;
  preserve true offline access until connectivity is established, but do not
  render cached content after the client detects a connection and the check
  remains unresolved.
- A 404 for an old or unknown download id means the player cannot establish
  freshness; require a new download. Do not infer that the lesson is safe.

## Device acceptance

1. Download a lesson, go offline, and verify it opens before expiry.
2. Hold one of its sections on the server. Reconnect and verify the status
   request precedes any cached-content read; the old package is removed.
3. Verify a new package omits the held section.
4. Move the device clock beyond `expiresAt` while offline; it must not open.
   Test clock rollback too and record the limitation of device-local time.
5. Verify a checker outage shows the temporary retry wording, not a
   safeguarding warning, and that a held picture leaves teaching text intact.

An offline device cannot be remotely revoked until its next connection.
That bounded window remains a residual risk, not a claim of instant removal.
