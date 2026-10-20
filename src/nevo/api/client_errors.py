"""Somewhere for a crash to go. SCRUM-215's neighbour, ask B36.

The error screens promise "We're on it". Until now there was nowhere to be on
it from: a client-side crash went to the browser console and no further, so
the promise was not true and nobody could have known it was broken.

This is deliberately small. It is not analytics and it is not a log pipeline -
it is the one thing the screen needs, which is a reference the person can
quote and that we can find afterwards.
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, status
from pydantic import BaseModel, ConfigDict, Field

from nevo.api.auth import OptionalPrincipalDependency
from nevo.content_parsing.failures import new_incident

logger = logging.getLogger("nevo.client_errors")

router = APIRouter(prefix="/api/v1", tags=["support"])


class ClientErrorReport(BaseModel):
    """What a screen can say about its own crash.

    Nothing about the child. A stack trace and a route are about our code; a
    lesson's text, a question, or anything the learner typed is not, and none
    of it helps us find the fault. The field list is closed for that reason
    rather than taking a free bag of context.
    """

    model_config = ConfigDict(populate_by_name=True)

    #: What broke, in the words the runtime used.
    message: Annotated[str, Field(min_length=1, max_length=2_000)]
    #: Where it broke. The app's own route, not a full URL - a URL can carry
    #: a token or an identifier in its query string.
    route: Annotated[str | None, Field(default=None, max_length=300)] = None
    stack: Annotated[str | None, Field(default=None, max_length=20_000)] = None
    #: Which build, so a crash can be tied to a release rather than to a day.
    app_version: Annotated[str | None, Field(default=None, alias="appVersion", max_length=80)] = (
        None
    )
    surface: Literal["student", "teacher", "admin", "parent", "unknown"] = "unknown"
    #: The reference the screen already showed the person, where it had one.
    #: Sent back so a report and the 500 that caused it meet in the log.
    incident_id: Annotated[str | None, Field(default=None, alias="incidentId", max_length=40)] = (
        None
    )


class ClientErrorAccepted(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    #: Quote this. It is the same twelve hex characters an unhandled 500
    #: carries, so a person reporting a problem does not have to know which
    #: kind of failure they met.
    incident_id: str = Field(alias="incidentId")
    received_at: datetime = Field(alias="receivedAt")


@router.post(
    "/client-errors",
    response_model=ClientErrorAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def report_client_error(
    payload: ClientErrorReport,
    principal: OptionalPrincipalDependency,
) -> ClientErrorAccepted:
    """Take a crash report from a screen and give back a reference.

    Unauthenticated on purpose: a crash on the sign-in screen is a crash, and
    requiring a session would lose exactly the reports we most want. The
    account is not included in the application log, even when signed in.

    Accepted rather than created - this is a log line, not a record anybody
    can read back. There is deliberately no endpoint to list these: a store of
    client crashes that staff can browse becomes a store of whatever those
    crashes happened to contain. Raw messages, routes and stacks are discarded
    by this handler rather than sent to application logging.
    """

    incident = (
        payload.incident_id
        if payload.incident_id and re.fullmatch(r"[0-9a-f]{12}", payload.incident_id)
        else new_incident()
    )
    received = datetime.now(UTC)
    # Browser-controlled exception text can contain answers or identifiers.
    # Log only closed metadata and fingerprints, never raw text or account IDs.
    error_kind = next(
        (
            kind
            for kind in (
                "TypeError",
                "ReferenceError",
                "RangeError",
                "SyntaxError",
                "NetworkError",
                "AbortError",
                "Error",
            )
            if payload.message.startswith(kind + ":")
        ),
        "client_error",
    )
    logger.error(
        "client error %s (%s, %s)",
        incident,
        payload.surface,
        error_kind,
        extra={
            "incident_id": incident,
            "surface": payload.surface,
            "error_kind": error_kind,
            "route_fingerprint": hashlib.sha256((payload.route or "").encode()).hexdigest()[:16],
            "build_fingerprint": hashlib.sha256((payload.app_version or "").encode()).hexdigest()[
                :16
            ],
            "has_stack": bool(payload.stack),
        },
    )
    return ClientErrorAccepted(incidentId=incident, receivedAt=received)
