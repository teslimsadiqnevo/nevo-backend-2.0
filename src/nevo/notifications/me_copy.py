"""Words a /me learner or guardian reads in an email, as Lydia wrote them.

APPROVED, 24 November 2026: docs/me/Nevo_Me_Copy_24Nov.md is the string
sheet, every /me string with the rules that govern it. Build to it exactly;
a change of wording is a change to that sheet first, and Lydia's to make.

Voice: plain, second person, calm. No fragments. No em dashes. Never
alarming on a refusal, never scolding on a delay.

Only the strings the backend sends live here. The screens (the guardian
field, the waiting screen, the 14-day message, the refusals, the locked
progress screen, calibration) are the app's, built from the same sheet.
"""

APPROVED = True

# -- Identity ---------------------------------------------------------------

VERIFY_SUBJECT = "Your Nevo verification code"


def verify_paragraphs(*, first_name: str | None, code: str, minutes: int) -> list[str]:
    return [
        f"Hello {first_name or 'there'}, your Nevo verification code is {code}. "
        f"It works for the next {minutes} minutes. If you did not sign up for Nevo, "
        "you can ignore this email and nothing will happen."
    ]


def verify_text(*, first_name: str | None, code: str, minutes: int) -> str:
    return "\n\n".join(verify_paragraphs(first_name=first_name, code=code, minutes=minutes)) + "\n"


# -- Guardian consent ---------------------------------------------------------


def guardian_subject(*, learner_first_name: str | None) -> str:
    return f"{learner_first_name or 'A learner'} needs your consent to use Nevo"


def guardian_paragraphs(*, learner_first_name: str | None) -> list[str]:
    name = learner_first_name or "A learner"
    return [
        "Hello,",
        f"{name} has named you as their parent or guardian. They want to use Nevo to "
        "study their own course material, and because they are under 18 we need your "
        "consent before they can upload anything.",
        "Nevo teaches a lesson to one learner at a time, adapting the level, pace and "
        "format as it reads how they are working.",
        "You do not need to create an account. The page below explains what Nevo does "
        "with their work and asks you to agree to it.",
    ]


GUARDIAN_CTA = "Read and give consent"


def guardian_footnote(*, learner_first_name: str | None) -> str:
    name = learner_first_name or "they"
    return (
        "If you were not expecting this, you can ignore this email and "
        f"{name} will not be able to upload anything."
    )


def guardian_text(*, learner_first_name: str | None, link: str) -> str:
    return (
        "\n\n".join(
            [
                *guardian_paragraphs(learner_first_name=learner_first_name),
                f"{GUARDIAN_CTA}: {link}",
                guardian_footnote(learner_first_name=learner_first_name),
            ]
        )
        + "\n"
    )


# -- Billing -----------------------------------------------------------------

RENEWAL_CTA = "Buy another month"


def renewal_subject(*, ends_on: str) -> str:
    """Seven days before the month ends."""

    return f"Your Nevo month ends on {ends_on}"


def renewal_paragraphs(*, first_name: str | None, ends_on: str) -> list[str]:
    return [
        f"Hello {first_name or 'there'}, your Nevo month ends on {ends_on}. Nothing renews "
        "on its own, so if you want to keep going, buy another month before then and "
        "your lessons carry on without a break."
    ]


RENEWAL_FOOTNOTE = "Your work and your progress stay where they are either way."

LAPSED_SUBJECT = "Your Nevo month ended today"


def lapsed_paragraphs(*, first_name: str | None) -> list[str]:
    return [
        f"Hello {first_name or 'there'}, your Nevo month ended today. Your work and your "
        "progress are all still here. Buy another month whenever you are ready and you "
        "pick up exactly where you left off."
    ]


# -- Lessons -----------------------------------------------------------------

#: A /me learner's own upload that could not be prepared. Replaces the
#: teacher-facing failure text, which assumes a teacher and a review.
COULD_NOT_PREPARE = (
    "Nevo could not prepare this one. Try uploading it again, and if it still does "
    "not work, send it to us and we will look at it."
)


def hard_refusal_message(*, category: str | None, page: int | None) -> str | None:
    """Lydia's hard-tier refusal, for the one category it was written for.

    Her sentence names what the passage does, so it fits self-harm alone.
    Other hard categories have no approved wording yet and return None
    rather than a guess: the app shows its own generic refusal until Lydia
    writes theirs.
    """

    if category != "self_harm" or page is None:
        return None
    return (
        f"Nevo can't teach this one. The passage on page {page} tells a reader to harm "
        "themselves and keep it from an adult, and that isn't something Nevo will teach. "
        "If you think that's wrong, send it to us and we'll look at it."
    )
