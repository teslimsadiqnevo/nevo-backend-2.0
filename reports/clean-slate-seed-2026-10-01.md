# Clean slate: the reset, and everything in the new database

**1 October 2026** · Supabase `aws-0-eu-west-1` / `postgres` · served by
`https://nevo-backend-2-0-kn3d.onrender.com`

The database was emptied and rebuilt on Lydia's instruction, so everything from
here runs against one coherent school rather than ten months of accumulated
test rows.

> **The old data is not gone.** Full dump at
> `backups/pre-reset-20261001-234008.sql` (4.0 MB, 160 tables' worth). It
> restores with `psql`. Keep it until nobody wants the old records.

---

## The school

| | |
|---|---|
| **Name** | Brightwater Academy |
| **School code** | **`V4SE`** |
| URL slug | `brightwater-academy` |
| Academic session | 2026/2027 |
| Invoice | `NEVO-SEED-2341CE` — ₦22,575.00, **paid** |

The invoice is already paid, so the school is past the payment gate and its
workspace is open. It is not sitting in onboarding.

---

## Sign in

**Everyone's password and PIN is written here on purpose.** This is a test
database and a credential nobody can find is a credential nobody can test
with.

### Admins and staff — `POST /api/v1/auth/login/password`

| Who | Email | Password | Holds |
|---|---|---|---|
| Head / founding admin | `head@brightwater.example.com` | `NevoSeed!2026` | Every scope except learning support |
| Learning support | `senco@brightwater.example.com` | `NevoSeed!2026` | Learning support only |
| Teacher — Bisi Bello | `bisi.bello@brightwater.example.com` | `NevoTeach!2026` | Maths + Basic Science, JSS 1A & JSS 2B |
| Teacher — Femi Adeoye | `femi.adeoye@brightwater.example.com` | `NevoTeach!2026` | English, JSS 1A & JSS 3A |
| Teacher — Grace Ndukwe | `grace.ndukwe@brightwater.example.com` | `NevoTeach!2026` | Basic Technology, JSS 3A |

The two admins are split deliberately: the founding admin has every scope
**except** learning support, because the deepest view of every child should be
granted to a person on purpose rather than fall to whoever signed the school
up. The learning-support admin is who holds it.

### Children — `POST /api/v1/auth/login/pin`

**PIN for every child: `4820`.** Send the school code with it — an admission
number is only unique within a school.

| Name | Student ID | Class | Consent | Age |
|---|---|---|---|---|
| Amara Okafor | `BWA/2026/001` | JSS 1A | **given** | 12 |
| Tunde Bello | `BWA/2026/002` | JSS 1A | **given** | 12 |
| Chidi Eze | `BWA/2026/003` | JSS 1A | **given** | 11 |
| Sade Adeyemi | `BWA/2026/004` | JSS 2B | **given** | 13 |
| Nneka Obi | `BWA/2026/005` | JSS 2B | **pending** | 13 |
| Yusuf Lawal | `BWA/2026/006` | JSS 3A | **withdrawn** | 14 |

The last two are not oversights. Pending and withdrawn are the two states the
console has screens for and previously had nothing to test against:

- **Nneka** — a guardian who has not replied yet. The child waits.
- **Yusuf** — a guardian who withdrew. Per Lydia's ruling he **signs in
  normally** and is shown a suspended screen; what he cannot do is learn.

### Parents — `POST /api/v1/auth/login/password`

**Password for every guardian: `NevoParent!2026`.**

| Guardian | Email | Child |
|---|---|---|
| Ngozi Okafor | `ngozi.okafor@example.com` | Amara |
| Bisi Bello | `bisi.bello@example.com` | Tunde |
| Uche Eze | `uche.eze@example.com` | Chidi |
| Kemi Adeyemi | `kemi.adeyemi@example.com` | Sade |
| Ifeoma Obi | `ifeoma.obi@example.com` | Nneka |
| Aisha Lawal | `aisha.lawal@example.com` | Yusuf |

---

## Verified against the live API, not just the database

```
POST /api/v1/auth/login/password  head@brightwater      → 200
POST /api/v1/auth/login/password  senco@brightwater     → 200
POST /api/v1/auth/login/password  bisi.bello@brightwater→ 200
POST /api/v1/auth/login/password  ngozi.okafor          → 200
POST /api/v1/auth/login/pin       V4SE + BWA/2026/001   → 200
POST /api/v1/student-entry/lookup V4SE + BWA/2026/001   → 200 consentState "given"
POST /api/v1/student-entry/lookup V4SE + BWA/2026/005   → 200 consentState "pending"
```

---

## What else is in there

**Classes** — JSS 1A (3 children), JSS 2B (2), JSS 3A (1).

**Subjects** — Mathematics, English Language, Basic Science, Basic Technology,
all on the school's list and mapped to Nevo's canonical rows. Each class
carries the subjects its teachers take, and each teacher carries their own
subject list, so the two lists agree.

**Teaching** — 7 teacher-class-subject assignments, all `co_teacher` /
`roster_sync`.

**Learning** — one lesson, *Adding fractions with the same denominator*, in
three segments (explanation, worked example, practice question), assigned to
the three children in JSS 1A. 12 concepts across the four subjects.

**Progress** — 24 mastery rows and 24 review schedules, spread deliberately
between 0.30 and 0.82 so the progress screens show a range rather than six
identical numbers. One review falls due today per child; the rest are spread
forward, so the review screen is neither empty nor entirely overdue.

**Compliance** — DPA version `2026-01` accepted by the head.

**Notifications** — one for each admin, so no console opens with an empty bell.

**Reference data restored from the dump**, not reinvented: 32 canonical
subjects, 4 subscription tiers, 39 prompt templates. These are seeded by
migrations and belong to them; writing a second copy into the seed script is
how two sources drift apart.

---

## How it was done, and how to do it again

```bash
.venv/bin/python scripts/seed_clean_slate.py   # empties every table, builds the school
.venv/bin/python scripts/seed_learning.py      # the lesson, concepts, mastery, reviews
```

Both scripts write through the application's own models rather than raw SQL,
because a seed that bypasses the constraints protecting real data proves
nothing. Three of them caught mistakes while this ran, and each one was the
constraint doing its job:

1. A parent link has to agree with itself about whether a parent account
   exists.
2. A **withdrawal carries the same record of who decided it as a confirmation
   does** — a withdrawal is a decision somebody made, not an absence of one.
3. FSRS difficulty runs 1 to 10, not 0 to 1.

`scripts/seed_clean_slate.py` truncates every table it finds in the model
metadata rather than a hand-written list, so a table added next month is
included without anyone remembering to add it.

---

## Two things to know

**The old school codes are gone, and so are the new ones you may have noted.**
Every code was regenerated when the four-character format shipped, and the
reset changed them again. Anything with a school code written into it — a test
fixture, a seed file, a Postman collection — needs `V4SE` now. This already
caught Olayinka's end-to-end tests once today.

**The reference data is the one thing not reproducible from code.** It came out
of the dump. If the database is reset again before those migrations are made
re-runnable, restore `canonical_subjects`, `subscription_tiers` and
`ai_prompt_templates` from a dump the same way, or subject resolution and
pricing will quietly have nothing to look up.
