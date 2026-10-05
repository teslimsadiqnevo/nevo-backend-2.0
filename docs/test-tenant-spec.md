# The E2E test tenant

The shared contract for the tenant CI signs into. Ask B66.

Two things live here: the fixed points, which never change and are safe to
write into a test, and the thresholds, whose exact values matter less than the
boundary they sit past.

Rebuild it with:

```bash
.venv/bin/python scripts/seed_e2e_tenant.py        # the tenant
.venv/bin/python scripts/seed_e2e_probe_student.py # the fixed sign-in
```

The second is idempotent and can be run on its own against an existing
tenant.

---

## Fixed points

These are the only identifiers safe to hardcode. Everything else in the
tenant is generated and moves on every rebuild.

| | Value |
|---|---|
| School name | `E2E Test Academy (not a customer)` |
| **Probe student login** | **`NV-E2E000`** |
| Probe student ID | `E2E/PROBE` |
| Probe student PIN | `4820` |
| All students' PIN | `4820` |
| Admin | `e2e.admin@e2e.example.com` / `NevoE2E!2026` |
| Learning support | `e2e.senco@e2e.example.com` / `NevoE2E!2026` |
| Teachers | `busy.` / `spare.` / `co.` / `invited.teacher@e2e.example.com` |

**The school code is not a fixed point.** It is generated, because the
four-character scheme has to be exercised and a hardcoded code has already
broken CI once. Read it from the registration response, or from
`backups/e2e-tenant-summary.json` after a rebuild. At the time of writing it
is `D6AM`.

The probe student has **consent given**, so tests can reach a lesson. A child
the tests cannot get past the consent gate is a child the tests cannot use.

---

## Why the numbers are what they are

Not a tidy school. A tidy school renders every screen and proves almost
nothing: every counting bug this console has shipped lived in the gap between
a number and the right number — a count capped at a page boundary, a count of
flags under the word "students", an absent value rendered as a zero, a partial
read rendered as a total. None of those shows itself unless the data crosses
the threshold that triggers it.

### Students and consent

40 students, spread so that two different questions give two different
answers:

| State | Count | Why |
|---|---|---|
| confirmed | 20 | the ordinary case |
| pending | 8 | drives "waiting on parent consent" |
| not_sent | 8 | must **not** appear in that row — a different claim |
| withdrawn | 3 | the only state that stops processing |
| no consent record at all | 1 | "unknown" must not render as "nobody asked" |

"Without recorded consent" is everything but confirmed (20); "withdrawn" is 3.
On a uniform tenant those two coincide and a conflation bug is invisible.

The last row is what exercises the NDPA coverage figure, which refuses to show
a number if any student comes back without a consent record.

### Attention flags

240 flags across 8 children, a third acknowledged.

Two separate reasons. The Overview counts **children**, not flags, so equal
numbers would hide a bug that counts the wrong one. And `GET
/api/intelligence/flags` caps `limit` at 200, so 240 forces the paging loop
that a smaller tenant never runs.

### Adaptation events

250 events across 15 students, spread over the last 7 days.

`GET /api/admin/adaptation-log` caps `limit` at 100, and the SENCo screen pages
until it sees a short page. On a small tenant the first page is always short,
the loop exits immediately, and the multi-page path never executes. 250 forces
three pages. Spread across days rather than stacked at one instant, so date
filtering and ordering have something to do.

### Classes

8 classes, deliberately not all tidy:

- one archived — archiving is reversible and must not read as deleted
- one with no teacher at all — the "No teacher yet" state
- one with both a primary and a co-teacher
- the rest with a primary only
- assignment dates months apart, because they render on class and teacher
  detail and identical dates prove nothing

### Teachers

- one holding 5 classes, which forces the removal-reassignment flow
- one invited and never joined — no password, status `invited`
- one spare, on a single class

### SSO

A connected provider, and four sync runs: two clean, one `failed` with a
failure reason, one `partial_manual_review` with
`missingTeacherClassMappings: 4`. Six issues across the latter two.

The "View technical details" panel only renders when a run has issues or a
failure reason. With a clean history it never appears, and neither does the IT
Admin Home's "accounts couldn't be matched" row.

### Billing

One paid invoice, one unpaid with a due date 9 days out, a card on file, and a
contract with start and end dates against a real tier.

---

## What is deliberately absent

**No real children, no real names, no real contacts.** Every figure the console
renders is an aggregate or a state; nothing depends on the data being
plausible as people. Synthetic names throughout, and the school is named as
not a customer so it cannot be mistaken for one in a listing.

**No compliance findings.** The non-zero state has never been seen with real
data, and it is not worth contriving if it means putting a clinical term in a
database.

**No roster observations.** The count / null-count / absent variants are not
seeded yet: they are derived from lesson sessions rather than stored, and
whether the absent case is reachable at all needs checking before anything is
built against it.

---

## Keeping this honest

`tests/test_e2e_seed_thresholds.py` asserts each threshold against the API
limit it sits past, reading both from the source rather than from a number
written here. If a limit changes and the seed does not, that test fails rather
than the tenant quietly stopping testing the thing it exists to test.

If the tenant and this document disagree, the document is wrong — the scripts
are what runs.
