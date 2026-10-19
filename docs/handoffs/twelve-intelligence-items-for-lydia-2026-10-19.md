# The twelve intelligence items for Lydia

19 October 2026. These are the original twelve audit items, not twelve new
unresolved bugs. Existing engine priority is unchanged: items 7, 9 and 10 belong
inside the engine work already first. The other nine deepen existing work; none
is being placed above the engine.

1. **Baseline measurement reduction.** Convert the observed span, processing,
   reading, numerical and attention task results into distinct delivery settings;
   correct timing for the device/motor baseline, distinguish missing/declined tasks
   from misses, and preserve unrelated measurements on partial updates. Backend
   arithmetic and missingness fixes are shipped. Age-band/device calibration,
   complex-span task validation and oral-reading scoring remain specialist work;
   no validated psychometric measurement is being claimed.

2. **Warm-up recalibration.** Make the opening activity update the dimension it
   actually measured, rather than only recording completion. Domain questions are
   server-marked and device-result recalibration is idempotent; receipts distinguish
   recalibrated, unavailable and completion-only. Backend is shipped; the frontend
   must send actual device trial results to obtain a measurement.

3. **Adaptive knowledge probe using IRT.** Select questions by expected information
   and update a Rasch 1PL posterior from historical item difficulties, with bounded
   run length and uncertainty-based stopping. This is implemented locally. Question
   difficulty parameters are provisional and still need empirical calibration.
   One subject completes module 4; no-bank placement is explicitly unestablished,
   conservative and reopens when a bank becomes available in the staged follow-up.

4. **Actual Bayesian knowledge tracing.** Replace exponential score adjustments
   with BKT's prior, guess, slip and learning-transition update. This is running
   locally, versioned, and driven by saved marked evidence; unsupported or hinted
   success does not inflate mastery. Parameter validation is still outstanding.

5. **Genuine AKT rather than an architecture name.** Evaluate and train a compatible
   attention-based knowledge-tracing model, including the difference between stock
   AKT and Nevo's proposed separate reading-confound attribution. The current code
   does not pretend to be trained AKT. pyKT has been identified; hosting, lawful data
   preparation, evaluation, shadow inference and promotion are documented and await
   approval. Local BKT continues without waiting for this.

6. **Curriculum prerequisites and assessed-content mapping.** Connect authored
   concepts to questions/sections, enforce approved prerequisite links, and choose
   assigned work whose prerequisites are satisfied. Backend mapping/readiness
   tooling, cycle checks and deliverable next-work routing are implemented. Schools
   or subject owners still need to supply/approve the actual prerequisite graph
   and author checks where content genuinely lacks them; we will not invent it.

7. **Progressive scaffold fading - inside the first engine work.** Start from the
   frozen session support level, reduce support after three distinct qualifying
   unaided problems, avoid rewarding hint reliance, and restore support when the
   child struggles. Prevent duplicate callbacks or repeated answers from counting
   as fresh independent successes. Backend is implemented and tested; the player
   must render returned support changes in the demo.

8. **Delivery that consumes inferred pacing.** Return reading groups based on the
   frozen settings, preserve immutable chunk/annotation anchors online and offline,
   use the attention window in break monitoring, and expose authored-check gaps.
   Backend is implemented. Browser consumption and authorship of missing checks
   remain distinct tasks; the client should not manufacture content.

9. **Simplify/Expand fidelity and professional review - inside the first engine
   work.** Check source claims, equations and numerical content; preserve annotations;
   withhold unapproved variants from students; let a named teacher edit and approve
   the material. Automated checks are shipped but are not proof of semantic
   equivalence. The new lesson-wide sign-off and rewrite editor are staged until
   after the demo; teacher judgement remains required.

10. **Calculation marking - inside the first engine work.** Preserve the offered
    choices during server marking, restrict accepted aliases to the correct answer,
    reject distractor aliases in legacy data, and save calculation attempts through
    the correct database constraint. Valid calculations use deterministic interactive
    scaffolds, not generated pictures. Backend fixes are shipped and tested; the
    actual step-by-step player remains an end-to-end demo check.

11. **Evidence-based spaced repetition.** Derive review outcomes from persisted
    first attempts, final attempts, timing and hints; update an existing schedule
    transactionally once per concept/session; resist client verdicts, duplicate
    completion and stale/backdated evidence. This is implemented, including ordering
    by attempt number rather than random UUIDs for bulk/offline saves.

12. **Learner-safe intelligence responses.** Keep numerical mastery/reading estimates,
    internal weights and memory parameters out of student responses while retaining
    functional feedback and required player directives. This is implemented and the
    nullable contract is documented. Frontend handling still needs browser checks;
    this is not a claim that every surface or logging pipeline has been audited.

Separate from these twelve: the raw-interaction transport/retention questions
raised for the legal documents have their own verified limitations and are not
silently marked fixed by the lesson-review redesign.
