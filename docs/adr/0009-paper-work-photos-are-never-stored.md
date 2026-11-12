# ADR 0009: A paper-work photo is never stored

- Status: Accepted, signed off by Lydia 12 November 2026
- Date: 2026-11-12
- Owners: Nevo backend team

## Context

The typed, no-camera paper-work route exists (`af516a8`, 30 October):
`POST /api/v1/students/me/lessons/{lesson_id}/paper-work/typed` takes up to
eight step answers, marks them against the approved steps and returns
`countsAsCheckPass` false. §6 of Lydia's 28 October document also asks for a
camera route that reads a photograph of a child's working. Nothing implements
that yet.

A photograph of an exercise book taken in a classroom will catch faces, hands,
other children's work and the school's name. Every day, with nobody intending
it.

This ADR is written before the route, deliberately. The rule is far easier to
hold from the start than to impose on a photo store that already exists and
that something already depends on, and the argument that it is hard to add
later cuts both ways.

## Decision

Nevo reads the working, keeps the step marks, and discards the image. The step
marks are the record, and they are what everything downstream reads, so storing
the photograph buys nothing.

"Never stored" means all of the following, and the list is the decision rather
than a gloss on it:

1. The image is never written to disk.
2. It is never put in the media bucket.
3. It never reaches a backup.
4. It is held for the read and then gone.
5. **It is not kept on a failure either.** A photo Nevo could not read is
   discarded like any other, and the child takes another one. Keeping
   unreadable images to debug with is the loophole that always turns up in
   this rule, and it would mean the photographs we hold are exactly the ones
   that went wrong.
6. No thumbnail, and no cache of our own. Whatever the child's device keeps in
   its camera roll is theirs rather than ours.

Two things are built with the route rather than after it.

**A refusal always leaves a way forward.** This check will refuse good
photographs, the way every check we have does, and a child refused twice with
no route onward is stuck in the middle of a lesson. The camera route falls back
to the typed route.

**The wording when a photo has a person in it** is fixed, and is Lydia's:

> There is someone in this photo, so Nevo has not read it. Take another one of
> just your working.

It says what happened and what to do. Nothing about faces, nothing about
detection, no apology, and no suggestion the child did anything wrong.

## Consequences

The gateway cannot currently send an image at all. `ProviderRequest` carries
`system_instruction` and `user_content: str` and nothing else; the safety guard
reviews images through its own direct call rather than through the gateway. So
reading the working needs image input added to `ProviderRequest` and to the
Claude provider. That is the substantial part of the work, and it is a new
capability rather than a new route.

The person check can reuse `ContentSafetyGuard.check(text, image=...)`, which
already reviews an image and the text inside it. It needs its own phase: the
existing image phases judge pictures Nevo drew, not a photograph of a child's
book, and that phase's policy is Lydia's to word.

Marking reuses the typed route unchanged - same approved steps, same marking,
same `countsAsCheckPass` false.

Because the image never lands anywhere, there is no retention rule to write for
it, nothing for the purge to reach, no object for a subject-access request to
return and nothing in a backup to restore. That absence is the point, and it is
cheaper than any of the controls the alternative would need.

## How this is held

`tests/test_a_paper_work_photo_is_never_stored.py` fails if the paper-work
module acquires a route that takes an image while also reaching storage, a
media service, or the filesystem. It is written before the route so that the
first change that would break the rule hits it, rather than a reviewer noticing
later or nobody noticing at all.
