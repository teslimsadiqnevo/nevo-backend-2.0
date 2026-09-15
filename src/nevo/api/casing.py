"""One spelling for the wire.

Nearly every response in this API is camelCase, and a few dozen were not:
they were written before the convention settled and kept their Python field
names. A client cannot tell which is which from the outside, so each one cost
somebody a debugging session - `accessToken` reads as undefined and the
mistake looks like an auth failure.

Applying this config gives a model camelCase on the wire while still
accepting its Python names on the way in, so a request body a client already
sends in snake_case keeps working.
"""

from pydantic import ConfigDict


def to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part.title() for part in tail)


#: Camel out, either spelling in.
CAMEL_CONFIG = ConfigDict(alias_generator=to_camel, populate_by_name=True)
