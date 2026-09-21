"""What the current request is, where a dependency cannot be given it.

An administrator who has not confirmed their email address may read the
console and may not write to it. The rule has to hold on the server, not in
the interface, and it applies to every write in the product - imports, class
creation, invitations, consent requests - so it belongs in the one funnel
every authenticated action already passes through rather than in each handler.

That funnel takes a principal and a session, not a request, so the method and
path are put here by middleware and read there. A context variable rather than
a global: requests are served concurrently, and a global would let one
request's method decide another's.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass

#: The methods that change something. HEAD and OPTIONS change nothing, and
#: GET that changes something is a bug of its own.
WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


@dataclass(frozen=True, slots=True)
class RequestFacts:
    method: str
    path: str

    @property
    def writes(self) -> bool:
        return self.method.upper() in WRITE_METHODS


_REQUEST: ContextVar[RequestFacts | None] = ContextVar("nevo_request", default=None)


def set_request(method: str, path: str) -> None:
    _REQUEST.set(RequestFacts(method=method, path=path))


def current_request() -> RequestFacts | None:
    """The request being served, or None off the request path.

    None where the work is a worker, a scheduled job or a test calling a
    helper directly. Those are not a person writing to the console, so a rule
    about what a person may write does not apply to them.
    """

    return _REQUEST.get()
