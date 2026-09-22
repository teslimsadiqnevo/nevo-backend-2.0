# Simplify and expand have content behind them

The adaptation engine has returned `action: "simplify"` and `action: "expand"`
since it was built. Nothing stood behind either word: a client got an
instruction and the one body of text the teacher uploaded. This closes that.

## What is written, and when

At parse time, beside the pictures and the narration, each segment gets two
rewrites of its own text:

- `simplified` — the same content in plainer language, shorter
- `expanded` — the same content with more worked detail, longer

Parse time, not request time, for the same three reasons the pictures are made
then: a child waiting mid-lesson for a model to write is a child waiting; a
teacher approves what a child sees and cannot approve text that does not exist
until it is shown; and the cost is known before the lesson is assigned rather
than unbounded per child per reread.

Measured on real lessons: about **$0.0225 a lesson**, roughly one per cent of
what a lesson already costs to parse.

Segments under 200 characters are skipped. A one-line definition rewritten
"more simply" is a one-line definition, and skipping them is most of the
saving.

## What is refused

A rewrite is checked against the segment it came from before it is kept:

- **Any figure not in the source is grounds for dropping it.** This is the
  check that matters. A child reading the simpler version of a worked example
  must not be reading a different sum. `1,500` and `1500` are the same number.
- The simplified one must actually be shorter and the expanded one longer, by
  at least ten per cent, or the call did not do what it was asked.
- Identical to the body, empty, or unparseable is refused.
- A deterministic fallback response is refused outright: it rewrites nothing,
  so keeping it would store the same text twice and tell a child one of them
  was simpler.

A refusal is never a failure of the lesson. The segment keeps the teacher's
own body, the parse run carries a note naming the segment, and `needsReview`
is **not** set — an unwritten rewrite is not a fault in the lesson.

## On the wire

`depthVariants` rides on the segment, everywhere segments are served,
including the offline package:

```json
"depthVariants": {
  "simplified": {"body": "..."},
  "expanded": {"body": "..."},
  "model": "claude-haiku-4-5"
}
```

Null, or a missing key, means fall back to the segment's `body`. It is always
there.

The keys are the engine's own action names, so a client holding a plan that
says `action: "simplify"` reads `depthVariants.simplified` without a lookup
table.

## The engine will not ask for what you do not have

`POST /api/intelligence/adapt` accepts an optional `availableDepths` per
segment:

```json
{"id": "seg-3", "segmentType": "explanation",
 "availableModalities": ["text"], "availableDepths": ["simplified"]}
```

Send it and the engine withholds a `simplify` or `expand` the segment has no
text for. A client that receives `simplify` and has nothing simpler either
shows the same words again — which reads as the adaptation having done
nothing — or shows an error, which reads as a fault.

Omitting the field and sending `[]` are different answers. Omitted means "I
did not say", and the engine behaves exactly as it always has, so every client
written before this is unaffected. `[]` means "I looked, there is nothing".

## What did not change

Every gate stays where it was: three aligned signals across two categories,
0.60 confidence for the first adaptation and 0.70 after a shift, 90 seconds of
dwell, a 120-second cooldown, three shifts a session. This adds content behind
a decision; it does not make the decision easier to reach.
