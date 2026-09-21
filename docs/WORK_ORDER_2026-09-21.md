# Backend work order, 21 September 2026

Every backend ticket filed on 19 and 20 September, in the order it should be
built. The order is: what stops a demonstration, then what unblocks the
frontend, then what nobody is waiting on. A ticket that unblocks Yinka outranks
one that does not, because his work stops until it lands.

Status column is updated as each lands.

## 1. Stops the Monday walkthrough

| # | Ticket | What it is | Blocks | Status |
|---|--------|------------|--------|--------|
| 1 | SCRUM-154 | Parent onboarding link 404s: the backend builds the wrong path for the consent email | nobody, but it is on the walkthrough path | done |
| 2 | SCRUM-153 (backend) | Lesson review: per key point, the source text, what was extracted and a confidence signal, plus accept and amend | SCRUM-153, Yinka's only in-progress ticket | done |

## 2. Unblocks the frontend

| # | Ticket | What it is | Blocks | Status |
|---|--------|------------|--------|--------|
| 3 | SCRUM-148 | Class creation, bulk create, name normalisation, per-row import detail. Classes are derived from the uploads. | SCRUM-149 | done |
| 4 | SCRUM-150 | Admin email confirmation: issue, verify, expiry, resend, change address. Expired, already-confirmed and invalid are distinct. | SCRUM-151 | done |
| 5 | SCRUM-156 | Onboarding funnel: derive, stage, confirm, price, pay, then activate. Nothing reaches anyone before payment. | SCRUM-157 | done |
| 6 | SCRUM-158 | Written consent route beside digital, and the correct consenting party on the record | SCRUM-159 | done |
| 7 | SCRUM-165 | Learning support role: unheld by default, granted deliberately, refused by the API | SCRUM-166 | done |
| 8 | SCRUM-168 | Student entry: the link resolves identity, age is derived from the roster, consent is enforced server-side | SCRUM-167, SCRUM-171, part of SCRUM-160 | done |
| 9 | SCRUM-170 | Staff annotations against the export with an approval state, and dated accommodation history | SCRUM-164 SC-03 and SC-04 | done |

## 3. Nobody is waiting

| # | Ticket | What it is | Status |
|---|--------|------------|--------|
| 10 | SCRUM-163 | Transformation metrics for a class and a school. The per-student endpoint must not be built. | done |
| 11 | SCRUM-162 | Parent contact is email only: drop the phone column, drop SMS, drop Termii | done |
| 12 | SCRUM-161 | Slow lesson processing. Largely answered by commit ded5548. | answered |

## The school agreement's four consent obligations

Not in Jira, and nobody owned them. All four are built.

| Item | What landed | Status |
|------|-------------|--------|
| Thirty-day consent expiry | Link lasts 30 days; a daily sweep records an unanswered request and removes the roster entry 30 days later, keeping a minimal refusal so the school does not ask again | done |
| Two-point age check | The parent confirms the child's date of birth; it is compared with the school's, a disagreement blocks entry and waits for a person | done |
| Cross-border transfer consent | Its own consent type, asked alongside the first, granted on its own, nothing pre-selected | done |
| Withdrawal and objection in the platform | A parent withdraws, objects or asks for data from their own account, with no token and no expiry | done |

## Carried, not in Jira

- Date of birth on the roster. SCRUM-168 derives age from it and the school
  agreement's two-point age check needs it. Built once, under SCRUM-168.
- Lesson events are append-only in the database, so retention and erasure
  cannot be met. A pre-signing item.
- The API runs in Render's US West region although `render.yaml` asks for
  Frankfurt.
- AI call costs are recorded wrongly in `ai_gateway_calls`.
- The school agreement's Schedule 4 list: firewall, vulnerability scanning,
  point-in-time snapshots, multi-region failover, breach runbook, retention
  purge, 30-day consent expiry, cross-border consent, in-platform withdrawal,
  and the missing consent record fields.
