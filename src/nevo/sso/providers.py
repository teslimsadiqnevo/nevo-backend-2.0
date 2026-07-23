from urllib.parse import urlencode

import httpx

from nevo.domain.accounts.vocabulary import SsoProvider, UserRole
from nevo.sso.entities import (
    RosterSyncBatch,
    SsoProviderIdentity,
    SsoSchoolConfig,
)


class MicrosoftSsoProviderClient:
    def __init__(self, *, client_secret: str | None = None) -> None:
        self._client_secret = client_secret

    def authorization_url(
        self,
        *,
        config: SsoSchoolConfig,
        redirect_uri: str,
        state: str,
    ) -> str:
        tenant = config.tenant_id or "common"
        query = urlencode(
            {
                "client_id": config.client_id,
                "response_type": "code",
                "redirect_uri": redirect_uri,
                "response_mode": "query",
                "scope": "openid email profile User.Read",
                "state": state,
            }
        )
        return f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize?{query}"

    async def identity_from_callback(
        self,
        *,
        config: SsoSchoolConfig,
        code: str,
        redirect_uri: str,
    ) -> SsoProviderIdentity:
        if self._client_secret is None:
            raise LookupError("Microsoft SSO client secret is not configured")
        tenant = config.tenant_id or "common"
        async with httpx.AsyncClient(timeout=20) as client:
            token = await client.post(
                f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
                data={
                    "client_id": config.client_id,
                    "client_secret": self._client_secret,
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                },
            )
            token.raise_for_status()
            access_token = token.json()["access_token"]
            profile = await client.get(
                "https://graph.microsoft.com/v1.0/me",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            profile.raise_for_status()
        body = profile.json()
        return SsoProviderIdentity(
            provider=SsoProvider.MICROSOFT,
            external_id=str(body["id"]),
            email=str(body.get("mail") or body.get("userPrincipalName")),
            first_name=body.get("givenName"),
            last_name=body.get("surname"),
            role=UserRole.TEACHER,
        )

    async def roster_for_school(
        self,
        *,
        config: SsoSchoolConfig,
    ) -> RosterSyncBatch:
        del config
        raise LookupError("Microsoft roster sync requires tenant directory consent")


class GoogleSsoProviderClient:
    def __init__(self, *, client_secret: str | None = None) -> None:
        self._client_secret = client_secret

    def authorization_url(
        self,
        *,
        config: SsoSchoolConfig,
        redirect_uri: str,
        state: str,
    ) -> str:
        query = urlencode(
            {
                "client_id": config.client_id,
                "response_type": "code",
                "redirect_uri": redirect_uri,
                "scope": "openid email profile",
                "state": state,
                "hd": config.hosted_domain or "",
                "access_type": "offline",
                "prompt": "consent",
            }
        )
        return f"https://accounts.google.com/o/oauth2/v2/auth?{query}"

    async def identity_from_callback(
        self,
        *,
        config: SsoSchoolConfig,
        code: str,
        redirect_uri: str,
    ) -> SsoProviderIdentity:
        if self._client_secret is None:
            raise LookupError("Google SSO client secret is not configured")
        async with httpx.AsyncClient(timeout=20) as client:
            token = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": config.client_id,
                    "client_secret": self._client_secret,
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                },
            )
            token.raise_for_status()
            access_token = token.json()["access_token"]
            profile = await client.get(
                "https://openidconnect.googleapis.com/v1/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            profile.raise_for_status()
        body = profile.json()
        return SsoProviderIdentity(
            provider=SsoProvider.GOOGLE,
            external_id=str(body["sub"]),
            email=str(body["email"]),
            first_name=body.get("given_name"),
            last_name=body.get("family_name"),
            role=UserRole.STUDENT,
        )

    async def roster_for_school(
        self,
        *,
        config: SsoSchoolConfig,
    ) -> RosterSyncBatch:
        del config
        return RosterSyncBatch(students=(), teachers=())
