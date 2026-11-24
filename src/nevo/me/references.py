"""Which Paystack references belong to the /me band.

Its own module, importing nothing, because the payment service needs it and
nevo.me.billing imports the payment package: putting it there made a cycle
that only broke in some import orders.
"""

REFERENCE_PREFIX = "nevo-me-"


def is_individual_reference(reference: str) -> bool:
    return reference.startswith(REFERENCE_PREFIX)
