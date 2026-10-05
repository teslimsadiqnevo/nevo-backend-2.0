"""Somewhere for a crash to go. SCRUM-215's neighbour, ask B36.

The error screens promise "We're on it". Until now there was nowhere to be on
it from: a client-side crash went to the browser console and no further, so
the promise was not true and nobody could have known it was broken.

This is deliberately small. It is not analytics and it is not a log pipeline -
it is the one thing the screen needs, which is a reference the person can
quote and that we can find afterwards.
"""

from __future__ import annotations

import logging
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
    account is recorded when there is one.

    Accepted rather than created - this is a log line, not a record anybody
    can read back. There is deliberately no endpoint to list these: a store of
    client crashes that staff can browse becomes a store of whatever those
    crashes happened to contain.
    """

    incident = payload.incident_id or new_incident()
    received = datetime.now(UTC)
    # Logged, not stored. The one structured field is the reference; the rest
    # is for a person reading the log while they look into it.
    logger.error(
        "client error %s on %s (%s): %s",
        incident,
        payload.route or "unknown route",
        payload.surface,
        payload.message,
        extra={
            "incident_id": incident,
            "route": payload.route,
            "surface": payload.surface,
            "app_version": payload.app_version,
            "user_id": str(principal.user_id) if principal else None,
            "stack": payload.stack,
        },
    )
    return ClientErrorAccepted(incidentId=incident, receivedAt=received)
