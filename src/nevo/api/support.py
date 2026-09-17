"""Where a school goes when something is wrong.

Design ruled Help and support is one screen carrying three facts: an email, a
WhatsApp number, and how long an answer takes. None of the three lived in the
backend, so the console either hard-coded them or - as shipped - offered a menu
item that closed the menu and did nothing.

Served rather than embedded for the same reason the bank details are: a support
number that changes should change everywhere at once, and a number baked into a
released bundle is wrong until every client updates.
"""

import re
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from nevo.api.casing import CAMEL_CONFIG
from nevo.api.response_models import CamelResponse

router = APIRouter(prefix="/api/v1", tags=["support"])


class SupportSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    support_email: str = Field(
        default="support@nevolearning.com",
        validation_alias="SUPPORT_EMAIL",
    )
    support_whatsapp: str = Field(
        default="+234 906 467 8114",
        validation_alias="SUPPORT_WHATSAPP",
    )
    #: How long Nevo takes to answer, decided on 17 September rather than
    #: borrowed. The two response times already in the product are a sales
    #: promise on the landing page and a 48-hour NDPA data-rights obligation,
    #: and neither is a support commitment - publishing either as one would
    #: have made a promise to schools that nobody had agreed.
    #:
    #: The days are part of the promise. A message sent on Friday evening and
    #: answered on Monday keeps this one and breaks a bare "within 24 hours".
    support_response_time: str | None = Field(
        default="Mon\u2013Fri, we reply within 24 hours",
        validation_alias="SUPPORT_RESPONSE_TIME",
    )


class WhatsAppContact(CamelResponse):
    model_config = CAMEL_CONFIG

    #: As a person would read it aloud.
    number: str
    #: As a phone would dial it: digits only, no plus, no spaces. wa.me
    #: silently fails on anything else, which looks like a dead link.
    link: str


class SupportContactResponse(CamelResponse):
    model_config = CAMEL_CONFIG

    email: str
    whatsapp: WhatsAppContact
    #: Null until Nevo commits to one. A client showing nothing is honest; a
    #: client showing a number nobody agreed to is a promise to a school.
    response_time: str | None = None


def support_settings() -> SupportSettings:
    return SupportSettings()


SupportSettingsDependency = Annotated[SupportSettings, Depends(support_settings)]


def whatsapp_link(number: str) -> str:
    """wa.me wants the number in full international form, digits only."""
    return f"https://wa.me/{re.sub(r'[^0-9]', '', number)}"


@router.get("/support-contact", response_model=SupportContactResponse)
async def support_contact(settings: SupportSettingsDependency) -> SupportContactResponse:
    """How to reach Nevo when something has gone wrong.

    Public on purpose. A teacher who cannot sign in is exactly the person who
    needs this, and putting it behind the session they have lost would be the
    one place the screen must not fail.
    """
    return SupportContactResponse(
        email=settings.support_email,
        whatsapp=WhatsAppContact(
            number=settings.support_whatsapp,
            link=whatsapp_link(settings.support_whatsapp),
        ),
        response_time=settings.support_response_time,
    )
