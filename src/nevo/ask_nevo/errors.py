"""What Ask Nevo refuses, and why.

One error so far. It is deliberately not a generic failure: a person who has
used their day has not hit a fault, and telling them so would teach them that
the product breaks.
"""

from nevo.ask_nevo.allowance import Allowance


class AskNevoError(Exception):
    code = "ask_nevo_error"
    public_message = "Nevo could not answer that just now."


class AskNevoDailyLimitError(AskNevoError):
    """This person has used today's allowance.

    Carries the allowance so the caller can say when it comes back rather
    than leaving somebody to guess whether to keep trying.
    """

    code = "ask_nevo_daily_limit"

    def __init__(self, allowance: Allowance) -> None:
        super().__init__(allowance.message())
        self.allowance = allowance

    @property
    def public_message(self) -> str:  # type: ignore[override]
        return self.allowance.message()
