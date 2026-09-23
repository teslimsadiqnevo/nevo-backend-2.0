"""The staged upload routes hand on everything the ingest helper requires.

Both /api/v1/uploads and /api/v1/uploads/batch delegate to _ingest_one_file,
which needs a session factory because the parse outlives the request. Neither
route declared one, so neither could supply it, and every call raised a
TypeError before any work happened - a 500 in under a second on a route the
teacher console posts every lesson through.

Nothing caught it because the tests around these routes read the OpenAPI
document, and a handler that raises still has a perfectly good schema.

FastAPI resolves dependencies from the route handler's own signature and
nowhere else, so a helper's requirement has to be restated on every route
that calls it. That is the thing these tests hold.
"""

from __future__ import annotations

import inspect

from nevo.api.product_learning import (
    _ingest_one_file,
    staged_batch_upload,
    staged_file_upload,
    staged_upload,
)

#: What the route itself has to be handed, as opposed to what it works out
#: per file. Anything here that a route does not declare is a parameter
#: FastAPI will never inject and the call will never receive.
INJECTED = {"principal", "session", "parser", "sessions"}

ROUTES = (staged_file_upload, staged_batch_upload, staged_upload)


def required_of(function) -> set[str]:
    return {
        name
        for name, parameter in inspect.signature(function).parameters.items()
        if parameter.default is inspect.Parameter.empty
    }


def test_the_helper_still_needs_a_session_factory() -> None:
    # If this stops being true the tests below are guarding nothing.
    assert "sessions" in required_of(_ingest_one_file)


def test_every_upload_route_declares_what_it_must_hand_on() -> None:
    missing = {
        route.__name__: sorted(INJECTED - set(inspect.signature(route).parameters))
        for route in ROUTES
    }

    assert missing == {route.__name__: [] for route in ROUTES}


def test_both_delegating_routes_pass_the_factory_through() -> None:
    # Declaring it and forgetting to forward it fails exactly the same way.
    for route in (staged_file_upload, staged_batch_upload):
        assert "sessions=sessions" in inspect.getsource(route), route.__name__


def test_the_call_sites_satisfy_the_helper_signature() -> None:
    """Every required parameter of the helper is one the route can supply."""

    signature = inspect.signature(_ingest_one_file)
    for route in (staged_file_upload, staged_batch_upload):
        available = set(inspect.signature(route).parameters) | {"file", "filename", "subject"}
        unsatisfiable = required_of(_ingest_one_file) - available
        assert unsatisfiable == set(), (route.__name__, sorted(unsatisfiable))
    # Nothing is forwarded that the helper does not accept.
    assert "scope" in signature.parameters
