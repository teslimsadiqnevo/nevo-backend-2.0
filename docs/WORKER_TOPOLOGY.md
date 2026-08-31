# Worker topology

## What runs in the background today

Five background consumers start inside every web process:

| Consumer | Source of work | Concurrency safety |
| --- | --- | --- |
| `NotificationEmailWorker` | `notification_email_deliveries` | `SELECT ... FOR UPDATE SKIP LOCKED` |
| `ConsentDeliveryWorker` | `consent_notification_outbox` | `SELECT ... FOR UPDATE SKIP LOCKED` |
| `PostLessonProcessingWorker` | `post_lesson_processing` | `SELECT ... FOR UPDATE SKIP LOCKED` |
| `ScheduledJobRunner` | `scheduled_job_runs` | `pg_try_advisory_lock` per job |
| `HeartbeatLoop` / `SelfPingLoop` | timer only | idempotent |

All five hold their work in Postgres, not in memory. Every claim is either a
row lock or an advisory lock, so **running them on several web instances is
already safe**: a second instance either skips the locked row or fails to take
the job lock and moves on. Nothing is processed twice and nothing is lost when
an instance is replaced mid-deploy.

## Recommendation for multi-instance deployment

Correctness does not require a change. Operability does. The recommendation, in
priority order:

### 1. Split the schedule off the web tier first (highest value, lowest effort)

`ScheduledJobRunner` is the consumer whose work is spiky and slow — a roster
sync walks every connected school, and invoice collection makes an external
call per invoice. On the web tier, that competes with request handling for the
same event loop and the same database pool.

Run it as its own process with the same image and an env flag:

```
NEVO_ROLE=web       # serves HTTP, runs the fast outbox consumers
NEVO_ROLE=scheduler # runs ScheduledJobRunner only, one replica
```

Because the advisory locks are already in place, a botched rollout that leaves
both a web instance and a scheduler instance running the schedule is harmless —
it is a duplicate that loses the lock race, not a double execution.

### 2. Leave the outbox consumers on the web tier until volume justifies moving

Email, SMS, and post-lesson processing are short, I/O-bound, and already spread
across instances by `SKIP LOCKED`. Splitting them out adds a deployable without
buying throughput. Move them when a queue depth metric — not a hunch — says the
web tier is behind.

### 3. Add the operational surface that is genuinely missing

This is the real gap, and it is observability rather than architecture:

- **Alert on queue depth and age.** `consent_notification_outbox` and
  `notification_email_deliveries` rows in `queued`/`failed` older than an hour,
  and `post_lesson_processing` rows past `next_attempt_at`, mean a transport is
  down. Nothing currently pages anyone.
- **Alert on `scheduled_job_runs`.** A row whose `last_status` is `failed`, or
  whose `last_finished_at` is more than two intervals old, means a daily job
  has silently stopped. This table exists precisely so that check is a single
  query.
- **Surface the dead-letter tail.** Rows at `attempt_count >= MAX_ATTEMPTS` are
  never retried again. They are currently invisible; they should be a dashboard
  and an alert.
- **Handle a stuck `running` job.** If a scheduler process is killed
  mid-job, the advisory lock dies with its connection (so the next run is not
  blocked), but the row is left saying `running`. Treat `last_status = 'running'`
  with an old `last_started_at` as a failure in alerting.

### 4. Do not reach for a broker yet

Celery, RQ, or SQS would replace a working database-backed queue with a second
piece of infrastructure to operate, and would not remove the need for the
alerting in step 3. Revisit only when a job needs fan-out across many workers or
a retry policy the current backoff cannot express.

## Summary

The current design is safe to scale horizontally as-is. Split the scheduler into
its own process for isolation, add queue-depth and job-staleness alerting, and
leave the message brokers alone until measured volume calls for one.
