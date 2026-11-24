"""/me Phase 1b: a learner under eighteen nominates a guardian, who consents.

Learner routes live under /api/v1/me, so the route guard admits individual
accounts only. The guardian's two routes take a link token and no session:
the guardian never has an account.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field, field_validator

from nevo.api.auth import PrincipalDependency
from nevo.api.casing import CAMEL_CONFIG
from nevo.api.dependencies import DatabaseSession
from nevo.api.response_models import CamelResponse
from nevo.consent import guardian
from nevo.db.models.account import User
from nevo.db.models.consent import GuardianInvitation
from nevo.notifications import me_copy
from nevo.notifications.branding import render_email
from nevo.notifications.email import EmailDeliveryUnavailableError, ResendEmailDelivery
from nevo.notifications.links import guardian_consent_url

router = APIRouter(prefix="/api/v1", tags=["me"])


class GuardianInviteRequest(BaseModel):
    model_config = CAMEL_CONFIG

    contact: EmailStr
    #: Email only in January. The phone channel needs a sending provider that
    #: does not exist yet; it is the first thing added after launch.
    contact_method: Literal["email"] = "email"


class ConsentResponse(CamelResponse):
    """GET /me/consent: where consent stands, what it blocks, how to move."""

    required: bool
    state: Literal["not_required", "outstanding", "granted", "dormant"]
    guardian_contact: str | None = None
    invited_at: datetime | None = None
    last_sent_at: datetime | None = None
    dormant_since: datetime | None = None
    blocked: list[str] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)


class GuardianLinkResponse(CamelResponse):
    learner_first_name: str | None = None
    state: Literal["awaiting", "consented", "replaced"]
    consent_types: list[str]
    notice_version: str


class GuardianConsentRequest(BaseModel):
    """The guardian names themselves and ticks each consent on its own.

    Both ticks must be true: a lesson cannot be prepared without sending the
    material outside Nigeria, so consenting to one and not the other would
    open nothing. They stay two fields so the answer is specific to each.
    """

    model_config = CAMEL_CONFIG

    guardian_name: Annotated[str, Field(min_length=1, max_length=255)]
    guardian_contact: EmailStr
    relationship: Annotated[str, Field(min_length=1, max_length=80)] | None = None
    data_processing: Literal[True]
    cross_border_transfer: Literal[True]

    @field_validator("guardian_name", "relationship")
    @classmethod
    def _strip(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped


class GuardianConsentResult(CamelResponse):
    status: Literal["consented", "already_consented"]


def _view(view: guardian.ConsentView) -> ConsentResponse:
    return ConsentResponse(
        required=view.required,
        state=view.state,
        guardian_contact=view.guardian_contact,
        invited_at=view.invited_at,
        last_sent_at=view.last_sent_at,
        dormant_since=view.dormant_since,
        blocked=list(view.blocked),
        actions=list(view.actions),
    )


def _public(error: guardian.GuardianConsentError) -> HTTPException:
    detail: dict[str, object] = {"code": error.code}
    headers = None
    if isinstance(error, guardian.SendPaused):
        seconds = max(1, int((error.retry_at - datetime.now(UTC)).total_seconds()) + 1)
        detail["retryAt"] = error.retry_at.isoformat()
        headers = {"Retry-After": str(seconds)}
    return HTTPException(status_code=error.status_code, detail=detail, headers=headers)


async def _learner(session: DatabaseSession, principal) -> User:
    user = await session.get(User, principal.user_id)
    if user is None or user.role.value != "student":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail={"code": "student_required"})
    return user


async def _send(
    request: Request, learner: User, invitation: GuardianInvitation, token: str
) -> None:
    mailer = getattr(request.app.state, "email_delivery", None)
    if not isinstance(mailer, ResendEmailDelivery):
        return
    link = guardian_consent_url(mailer.frontend_base_url, token=token)
    try:
        await mailer.send(
            to=invitation.contact,
            subject=me_copy.GUARDIAN_SUBJECT,
            text=me_copy.guardian_text(learner_first_name=learner.first_name, link=link),
            html=render_email(
                heading=me_copy.GUARDIAN_SUBJECT,
                paragraphs=me_copy.guardian_paragraphs(learner_first_name=learner.first_name),
                cta=(me_copy.GUARDIAN_CTA, link),
            ),
        )
    except EmailDeliveryUnavailableError:
        # The nomination stands; resend is one button away.
        return


@router.get("/me/consent", response_model=ConsentResponse, response_model_exclude_none=True)
async def my_consent(principal: PrincipalDependency, session: DatabaseSession) -> ConsentResponse:
    learner = await _learner(session, principal)
    return _view(await guardian.consent_view(session, learner))


@router.post(
    "/me/guardian-invite",
    response_model=ConsentResponse,
    response_model_exclude_none=True,
    status_code=status.HTTP_201_CREATED,
)
async def invite_guardian(
    payload: GuardianInviteRequest,
    principal: PrincipalDependency,
    session: DatabaseSession,
    request: Request,
) -> ConsentResponse:
    """Name a guardian and send them the link. Also how a wrong contact is changed."""

    learner = await _learner(session, principal)
    try:
        invitation, token = await guardian.nominate(session, learner, contact=str(payload.contact))
    except guardian.GuardianConsentError as error:
        raise _public(error) from error
    await session.commit()
    await _send(request, learner, invitation, token)
    return _view(await guardian.consent_view(session, learner))


@router.post(
    "/me/guardian-invite/resend",
    response_model=ConsentResponse,
    response_model_exclude_none=True,
)
async def resend_guardian_invite(
    principal: PrincipalDependency,
    session: DatabaseSession,
    request: Request,
) -> ConsentResponse:
    learner = await _learner(session, principal)
    try:
        invitation, token = await guardian.resend(session, learner)
    except guardian.GuardianConsentError as error:
        raise _public(error) from error
    await session.commit()
    await _send(request, learner, invitation, token)
    return _view(await guardian.consent_view(session, learner))


@router.get("/guardian/{token}", response_model=GuardianLinkResponse)
async def guardian_link(token: str, session: DatabaseSession) -> GuardianLinkResponse:
    """The guardian's own view of the request. No session, no school."""

    view = await guardian.link_view(session, token)
    if view is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "guardian_link_invalid"})
    return GuardianLinkResponse(
        learner_first_name=view.learner_first_name,
        state=view.state,
        consent_types=list(view.consent_types),
        notice_version=view.notice_version,
    )


@router.post("/guardian/{token}/consent", response_model=GuardianConsentResult)
async def guardian_consents(
    token: str,
    payload: GuardianConsentRequest,
    session: DatabaseSession,
) -> GuardianConsentResult:
    """The guardian consents. Writes the learner's consent records; makes no account."""

    try:
        outcome = await guardian.give_consent(
            session,
            token,
            guardian_name=payload.guardian_name,
            guardian_contact=str(payload.guardian_contact),
            relationship=payload.relationship,
        )
    except guardian.GuardianConsentError as error:
        raise _public(error) from error
    if outcome is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "guardian_link_invalid"})
    if outcome == "replaced":
        raise HTTPException(status.HTTP_410_GONE, detail={"code": "guardian_link_replaced"})
    await session.commit()
    return GuardianConsentResult(status=outcome)
