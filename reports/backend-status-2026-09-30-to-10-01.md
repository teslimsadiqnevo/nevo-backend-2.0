# Backend status: 30 September – 1 October 2026

**From:** Teslim Sadiq (Backend)
**To:** Lydia Solomon (Product)
**Covers:** work completed since the tickets filed on 30 September

Everything below is deployed and working on the temporary API address
(`nevo-backend-2-0-kn3d.onrender.com`) while our main service is down. Nothing
here is waiting on a release.

---

## Summary

| Ticket | What it was | Status |
|---|---|---|
| SCRUM-201 | Four-character school code | Done |
| SCRUM-202 | Student ID / Admission Number as the child's identity | Done |
| SCRUM-203 | Import parser columns and rejection rules | Done |
| SCRUM-204 | OB-02: derived classes, class merges, rejected rows, subject spelling | Done |
| SCRUM-205 | Bank details served from configuration | Already built — closed |
| SCRUM-118 | Registration returning a 500 on valid input | Fixed |

Six of the eight tickets raised on 30 September are closed. The two still open
are **SCRUM-206** (needs a build decision, see *Open items*) and the front-end
tickets, which are Olayinka's.

---

## SCRUM-201 — The school code

A school's code is now four characters, from an alphabet that deliberately
leaves out `0`, `O`, `1` and `I`. A code read off a whiteboard and typed by a
seven-year-old can no longer land on the wrong school. Uniqueness is enforced
by the database itself, so two schools cannot end up sharing one.

**A decision I made that you may want to reverse.** Every existing school's
code was **regenerated** into the new shape rather than left as it was. 134
codes changed. My reasoning: a parent holding two schools' codes in two
different formats is exactly the confusion the short code exists to remove.

If you would rather the old ones had been kept, tell me this week — it is
reversible now, and will not be once a school has written one down or printed
it on anything.

---

## SCRUM-202 — A child's own ID

Children now sign in with the Student ID / Admission Number their school
already uses for them, instead of a code we invented and nobody had written
down anywhere.

- The ID is unique within a school, and capitalisation does not matter — a
  school writing `adm001` and `ADM001` means the same child.
- **Enrolment no longer asks for a child's email address.** Children do not
  have one, and asking was the reason schools were inventing them.
- Re-uploading a roster now recognises children it has seen before and keeps
  their history with them, rather than creating a second account for the same
  child.

The old sign-in field still works alongside the new one, so the console can
move over when it is ready rather than on the same day as this deploy.

---

## SCRUM-203 — The import parser

The student and teacher templates now carry the final columns. Two things
worth knowing:

**A school's old spreadsheet still works.** Last term's file with
`parent_email`, `student_id`, `surname`, `dob` and similar headings is
accepted and mapped to the new names rather than refused. Columns we have
retired are ignored, not rejected.

**Rejections name the line.** A bad row says which row number, which field,
what the value was and what to do — and the rest of the file proceeds. A
school with four hundred children will not notice thirty going missing, so the
file has to say.

Teacher rows now merge on email address, so a school that wrote one row per
subject gets **one teacher with several subjects** rather than several
teachers with one each.

---

## SCRUM-204 — OB-02, "What Nevo found"

This is the one with money attached, so in a little more detail.

**Classes are proposed, not guessed.** Where a file carries `JSS 2A`, `JSS2A`
and `JSS 2 A`, Nevo now says "these look like one class written three ways",
names the spelling it would keep and states the headcount the merged class
would carry. The admin confirms each one.

**"No, we really do run those separately" is a real answer** and is
remembered, so the same file is never questioned twice.

**Confirming is refused by the server while any of those questions is
unresolved** — not by hiding a button. As you put it, the headcount per class
becomes the invoice.

**Derived classes now show their subjects**, read out of the teacher file, so
a school can see what it is about to pay for.

**One correction to the ticket, in our favour.** You listed four spellings
(`JSS 2A`, `JSS2A`, `Jss 2a`, `JSS 2 A`). Capitalisation and double spaces
were already being folded, so `JSS 2A` and `Jss 2a` were never two classes —
three of the four reach the admin as a question, not four. Collapsing spaces
*entirely* is a guess about somebody's spacing, which is why it is asked
rather than applied.

### The subject spelling question, in D05

Built as specified, and in D05 rather than at OB-02.

- `Maths` and `Mathematics` are treated as **one subject from the moment of
  import**. That is the safe default: two would split a child's mastery across
  two knowledge graphs and halve their progress for no reason.
- The question is then asked on the classes screen, after payment, because a
  spelling does not change the invoice.
- Binary. **Same** keeps the fuller spelling. **Different** splits them back
  out with both labels exactly as the school wrote them.
- Where several pairs need settling they list together, not one pop-up at a
  time.
- **A subject Nevo does not recognise is never questioned.** The question is
  only ever raised where we can actually argue the two are the same word —
  a known short form, or one spelling being a long-enough prefix of the other.
  `Further Maths` against `Mathematics` is not a pair. `Art` against
  `Arithmetic` is not a pair.

---

## SCRUM-205 — Bank details from configuration

**Already built — I closed it rather than re-doing it.** The Kuda details come
from one place on the server and are served to whatever screen displays them.
Changing bank is one value, and no screen can ship a stale or placeholder
number.

**One thing to decide.** The live account number currently sits in our code
repository as the default value. That still satisfies the rule as written —
it is server configuration, not a front-end component. But if the intent was
that the real number exists only on the deployed server, say so and I will
move it, which takes about ten minutes. Worth settling before the repository
is shared with anyone outside the team.

---

## SCRUM-118 — Registration returning a 500

New school sign-up was failing on perfectly valid input. This was blocking all
new school onboarding, so it is the most urgent thing in this report.

Three separate faults on the one endpoint, all now fixed:

1. **If our email provider was slow or unreachable, sign-up failed** — even
   though the school's account had already been created successfully. The
   admin saw a failure, tried again, and the second attempt was rejected as a
   duplicate. So the account existed *and* could not be created. That is the
   3.6-second delay Olayinka reported.
2. **The confirmation email was being sent while the person waited**, which
   was most of those 3.6 seconds. It now goes out after the page responds.
3. **Leaving the admin's name blank crashed it**, reported as our fault rather
   than as a correction for the person to make.

---

## Two problems found while testing, and fixed

Neither was on a ticket. Both are worth knowing about.

**Our rate limiting was not working anywhere in the product, including on
sign-in.** Because of how our hosting routes traffic, every attempt was being
counted as if it came from a different person, so limits never triggered. I
measured it: seven attempts from one machine were counted as six different
people, and five wrong PINs in a row were all accepted for a sixth try. Now
fixed and verified.

**The child entry link never worked, for anyone.** The endpoint behind it was
built expecting links that name a specific child, and nothing in the system
ever created one — so every link returned "invalid". There were four such
links in the live database and none of them named a child. Nobody had reported
it because the flow it belonged to had not shipped.

This turned out not to matter, because **SCRUM-208 removes the link anyway**:
the child types the school code and their Student ID on one screen instead. So
rather than repair it, I built the lookup that 05 Entry actually needs. It is
live, and Olayinka is unblocked on it.

That lookup is unauthenticated by necessity — the child has no account yet.
So it never reveals whether an ID exists or which field was wrong, and it is
rate limited three ways, including a limit per school code that cannot be
worked around. I tested that limit against the live service: it holds at sixty
wrong guesses in fifteen minutes, which a classroom of children mistyping on
their first morning will never reach, and a roster enumeration passes in
seconds.

---

## Open items

**Needs a decision from you**

1. **SCRUM-206 — five upload stages.** Your ticket makes the call (five, not
   three, superseding SCRUM-138) so I am not blocked on the decision. What I do
   need to check before building is whether the pipeline genuinely has five
   distinguishable phases to report, or whether two of the five rungs would
   have nothing behind them — which your own rule forbids. I will come back
   with an answer on that rather than build a rung that cannot move.
2. **SCRUM-201** — regenerated school codes: keep, or revert to the old ones?
3. **SCRUM-205** — move the live account number off the repository, or leave it?
4. **SCRUM-138 and SCRUM-172** both need closing as redundant once 206 is
   settled, per your note on that ticket.

**Known gaps, not blocking**

- No student in the live database has an admission number yet — the field
  shipped yesterday and no roster has been imported since. So the new entry
  lookup returns "not found" for everyone at the moment, correctly. It comes to
  life on the first roster import.
- The canonical subject list is my own reasonable starting set from the
  Nigerian secondary curriculum, **not** the subject syllabuses in the
  curriculum research. It is loaded from the database rather than written into
  the code, so it can be replaced without a deploy when the real list is ready.
  Primary, Montessori and Cambridge subjects are knowingly absent, and a school
  can add its own in the meantime.
- Term **end** dates are still not modelled. Terms are treated as starting on
  the dates a school configures. I would rather make term length a school
  setting than hardcode thirteen weeks for everyone.

**Still on my side, unrelated to these tickets**

Our main API is suspended on bandwidth and the image-generation credits are
exhausted. I am working through both separately. The Nigerian voice provider is
back up.
