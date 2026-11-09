"""Whether a provider's last call actually worked, not whether a key is set.

``/health`` reported ``lessonImages: configured`` and ``lessonAudio:
configured`` throughout three days in which every image call came back
"credit_balance_exhausted" and every audio call came back 401. Configured means
a key is present. It says nothing about whether the provider accepts it, so the
one screen an administrator would look at was green while the feature was
entirely dead.

This records the outcome of the last call to each provider, in memory, as the
calls happen. Not a probe: probing on every health poll would mean paying a
provider to answer a monitoring question, and the answer would be stale the
moment nobody was uploading. What a parse already learns is enough.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock

logger = logging.getLogger(__name__)

#: Long enough that a quiet night does not read as an outage, short enough that
#: yesterday's success does not vouch for today.
STALE_AFTER_HOURS = 24

#: Failures that no retry will clear, because somebody has to pay.
#:
#: Worth telling apart from an outage: a 401 or a 500 may well be gone in ten
#: minutes, while "credit_balance_exhausted" will still be there tomorrow and
#: every lesson uploaded in between is missing its audio. The audio provider
#: ran out of credit before the 8 November demo and the first anyone knew was
#: a child opening a lesson with no narration.
BILLING = re.compile(
    r"credit|balance|quota|billing|payment|insufficient.funds|subscription|"
    r"exceeded.your.current|402",
    re.IGNORECASE,
)


def needs_a_human_with_a_card(detail: str | None) -> bool:
    """Whether this failure is about money rather than about the service."""
    return bool(detail and BILLING.search(detail))


@dataclass(frozen=True, slots=True)
class Outcome:
    """How the last call to one provider went."""

    ok: bool
    at: datetime
    #: Why it failed, trimmed. Never shown to a teacher; this is for whoever
    #: is looking at the status page.
    detail: str | None = None


class ProviderHealth:
    """The last outcome per provider, kept in memory and never persisted.

    In memory on purpose: it describes this process, and a restart genuinely
    does not know yet. "unknown" is the honest answer then, and it is a
    different answer from "working".
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._outcomes: dict[str, Outcome] = {}

    def record(self, provider: str, *, ok: bool, detail: str | None = None) -> None:
        with self._lock:
            previous = self._outcomes.get(provider)
            self._outcomes[provider] = Outcome(
                ok=ok, at=datetime.now(UTC), detail=(detail or None) and detail[:200]
            )
        # Said on the change, not on every call. Recording the outcome was
        # enough to make /health honest, but nobody watches /health, so the
        # audio provider sat out of credit until a child opened a lesson with
        # no narration. A line on the way down and a line on the way back up
        # is something a log alert can be pointed at; a line per call is noise
        # that an alert would have to be taught to ignore.
        was_working = previous is None or previous.ok
        if ok and not was_working:
            logger.warning("Provider recovered provider=%s", provider)
        elif not ok and was_working:
            if needs_a_human_with_a_card(detail):
                logger.error(
                    "PROVIDER OUT OF CREDIT provider=%s detail=%s - no retry will "
                    "clear this and every lesson uploaded until it is topped up "
                    "loses this feature",
                    provider,
                    detail,
                )
            else:
                logger.error("Provider failing provider=%s detail=%s", provider, detail)

    def state(self, provider: str) -> str:
        """``working``, ``failing``, or ``unknown``.

        ``unknown`` covers both "nothing has called it since this process
        started" and "the last thing we know is too old to rely on", because a
        client should treat those the same: do not claim it works.
        """

        with self._lock:
            outcome = self._outcomes.get(provider)
        if outcome is None:
            return "unknown"
        age = (datetime.now(UTC) - outcome.at).total_seconds() / 3600
        if age > STALE_AFTER_HOURS:
            return "unknown"
        return "working" if outcome.ok else "failing"

    def last_failure(self, provider: str) -> str | None:
        with self._lock:
            outcome = self._outcomes.get(provider)
        return None if outcome is None or outcome.ok else outcome.detail


#: One per process. The parse records into it; /health reads it.
PROVIDERS = ProviderHealth()

#: The names used in both places, so a typo cannot silently report "unknown"
#: for ever.
LESSON_IMAGES = "lesson_images"
LESSON_AUDIO = "lesson_audio"
