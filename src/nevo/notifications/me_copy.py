"""Words a /me learner reads, held in one place for Lydia.

DRAFT - NOT APPROVED. Lydia writes all learner-facing copy. These are
functional drafts so the code path can be built and tested; they reach
nobody while ME_REGISTRATION_ENABLED is off, and that flag is not to be
turned on until she has replaced or approved every string in this file.

Kept out of the handlers on purpose: a reviewer reads one file, and a change
of wording never touches the code that sends it.
"""

APPROVED = False

VERIFY_SUBJECT = "Your Nevo verification code"


def verify_text(*, first_name: str | None, code: str, minutes: int) -> str:
    greeting = f"Hello {first_name}," if first_name else "Hello,"
    return (
        f"{greeting}\n\n"
        f"Your Nevo verification code is {code}.\n\n"
        f"It works for {minutes} minutes. If you did not create a Nevo "
        "account, you can ignore this email.\n"
    )


def verify_paragraphs(*, first_name: str | None, code: str, minutes: int) -> list[str]:
    greeting = f"Hello {first_name}," if first_name else "Hello,"
    return [
        greeting,
        f"Your Nevo verification code is {code}.",
        f"It works for {minutes} minutes. If you did not create a Nevo account, "
        "you can ignore this email.",
    ]
