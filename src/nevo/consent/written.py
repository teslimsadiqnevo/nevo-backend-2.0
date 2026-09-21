"""The paper route, and the notice a parent actually signed.

A school with four hundred children will not get four hundred email replies.
Without a paper route the children whose parents did not answer cannot learn,
and the school blames Nevo rather than its own parents. Digital stays the
default - it produces the stronger record and gives Nevo a direct line to the
parent - and paper exists beside it.

Nevo supplies the form rather than the school writing one. A school's own
generic permission slip does not mention that lesson text is processed outside
Nigeria, and that is exactly the line a school cannot be left to draft.
"""

from __future__ import annotations

from nevo.intelligence.compliance_audit import render_simple_pdf

#: The version of the privacy notice this form carries. Stored on every
#: consent record taken against it, because "the parent consented" means
#: nothing without what they were shown when they did.
NOTICE_VERSION = "2026-09-v1"

#: Where lesson content is processed. Named rather than described, because a
#: parent consenting to a transfer out of Nigeria is entitled to know to whom.
PROCESSORS_OUTSIDE_NIGERIA = (
    "Anthropic (United States) - writes and adapts lesson material",
    "OpenAI (United States) - draws lesson illustrations",
    "YarnGPT - reads lesson text aloud",
)


def consent_form_lines(*, school_name: str, student_name: str | None = None) -> list[str]:
    """The form's text, so the wording is testable rather than only printable."""

    child = student_name or "________________________________"
    return [
        "Nevo parental consent form",
        f"School: {school_name}",
        f"Child's name: {child}",
        "",
        "Nevo helps your child learn by adapting lessons their teacher has",
        "written to the way your child learns best. Your school has asked for",
        "your permission before your child begins.",
        "",
        "What Nevo keeps: your child's name and class, the lessons they open,",
        "how long they spend on each part, and what they answer. Your child's",
        "work is used to help them learn and is shown to their teacher.",
        "",
        "1. I give permission for my child to use Nevo.",
        "   Signed: ______________________  Date: ______________",
        "",
        "2. SEPARATE PERMISSION - processing outside Nigeria.",
        "   Some lesson text is sent to these companies, which are outside",
        "   Nigeria, to write and read lesson material:",
        *[f"   - {processor}" for processor in PROCESSORS_OUTSIDE_NIGERIA],
        "   Tick and sign only if you agree to this.",
        "   [ ] I agree    Signed: ______________________  Date: ____________",
        "",
        "You can withdraw either permission at any time, and it is no harder",
        "than giving it: use the link in the email Nevo sends you, or tell",
        "your school and they will pass it on.",
        "",
        "Parent's name (please print): ______________________________",
        "Relationship to the child: _________________________________",
        "",
        f"Privacy notice version {NOTICE_VERSION}. Keep the top copy; return",
        "this page to the school office.",
    ]


def render_consent_form(*, school_name: str, student_name: str | None = None) -> bytes:
    """The printable form, generated here so every school's is the same one."""

    return render_simple_pdf(consent_form_lines(school_name=school_name, student_name=student_name))
