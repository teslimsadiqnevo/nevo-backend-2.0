from collections.abc import AsyncIterator
from urllib.parse import urlencode

import httpx

from nevo.domain.accounts.vocabulary import SsoProvider, UserRole
from nevo.sso.entities import (
    RosterAccount,
    RosterSyncBatch,
    SsoCloudFile,
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
                "scope": (
                    "openid email profile offline_access "
                    "https://graph.microsoft.com/.default"
                ),
                "prompt": "consent",
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
            token_body = token.json()
            access_token = token_body["access_token"]
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
        if self._client_secret is None or not config.tenant_id:
            raise LookupError(
                "Microsoft directory credentials need attention. Reauthorise the connection."
            )
        async with httpx.AsyncClient(timeout=30) as client:
            token = await client.post(
                f"https://login.microsoftonline.com/{config.tenant_id}/oauth2/v2.0/token",
                data={
                    "client_id": config.client_id,
                    "client_secret": self._client_secret,
                    "grant_type": "client_credentials",
                    "scope": "https://graph.microsoft.com/.default",
                },
            )
            _provider_response(token, "Microsoft directory authorization failed")
            headers = {"Authorization": f"Bearer {token.json()['access_token']}"}
            classes = [
                item
                async for item in _microsoft_pages(
                    client,
                    "https://graph.microsoft.com/v1.0/education/classes"
                    "?$select=id,displayName,externalId",
                    headers,
                )
            ]
            memberships: dict[str, set[str]] = {}
            accounts: dict[str, dict[str, object]] = {}
            for school_class in classes:
                class_ref = str(
                    school_class.get("externalId") or school_class.get("id") or ""
                )
                class_id = school_class.get("id")
                if not class_ref or not class_id:
                    continue
                members_url = (
                    "https://graph.microsoft.com/v1.0/education/classes/"
                    f"{class_id}/members?$select=id,displayName,givenName,surname,mail,"
                    "userPrincipalName,primaryRole"
                )
                async for member in _microsoft_pages(client, members_url, headers):
                    external_id = str(member.get("id") or "")
                    email = member.get("mail") or member.get("userPrincipalName")
                    if not external_id or not email:
                        continue
                    accounts[external_id] = member
                    memberships.setdefault(external_id, set()).add(class_ref)

        students, teachers = [], []
        for external_id, member in accounts.items():
            role = str(member.get("primaryRole") or "").casefold()
            account = _roster_account(
                external_id=external_id,
                email=str(member.get("mail") or member.get("userPrincipalName")),
                first_name=_text(member.get("givenName")),
                last_name=_text(member.get("surname")),
                role=UserRole.TEACHER if role == "teacher" else UserRole.STUDENT,
                class_ids=memberships.get(external_id, set()),
            )
            (teachers if account.role is UserRole.TEACHER else students).append(account)
        return RosterSyncBatch(students=tuple(students), teachers=tuple(teachers))

    async def download_file(
        self,
        *,
        config: SsoSchoolConfig,
        file_id: str,
        drive_id: str | None = None,
    ) -> SsoCloudFile:
        if not drive_id:
            raise LookupError("OneDrive import requires a drive id")
        if self._client_secret is None or not config.tenant_id:
            raise LookupError("Microsoft cloud file credentials need attention")
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            token = await client.post(
                f"https://login.microsoftonline.com/{config.tenant_id}/oauth2/v2.0/token",
                data={
                    "client_id": config.client_id,
                    "client_secret": self._client_secret,
                    "grant_type": "client_credentials",
                    "scope": "https://graph.microsoft.com/.default",
                },
            )
            _provider_response(token, "Microsoft file authorization failed")
            headers = {"Authorization": f"Bearer {token.json()['access_token']}"}
            base = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/items/{file_id}"
            metadata = await client.get(base, headers=headers)
            _provider_response(metadata, "OneDrive file was not found")
            content = await client.get(f"{base}/content", headers=headers)
            _provider_response(content, "OneDrive file download failed")
        body = metadata.json()
        return SsoCloudFile(
            filename=str(body.get("name") or f"onedrive-{file_id}"),
            content_type=str(body.get("file", {}).get("mimeType") or "application/octet-stream"),
            content=content.content,
        )


class GoogleSsoProviderClient:
    def __init__(
        self,
        *,
        client_secret: str | None = None,
        refresh_token: str | None = None,
    ) -> None:
        self._client_secret = client_secret
        self._refresh_token = refresh_token

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
                "scope": (
                    "openid email profile "
                    "https://www.googleapis.com/auth/classroom.courses.readonly "
                    "https://www.googleapis.com/auth/classroom.rosters.readonly "
                    "https://www.googleapis.com/auth/drive.readonly"
                ),
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
            token_body = token.json()
            access_token = token_body["access_token"]
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
            refresh_token=token_body.get("refresh_token"),
        )

    async def roster_for_school(
        self,
        *,
        config: SsoSchoolConfig,
    ) -> RosterSyncBatch:
        refresh_token = config.provider_credential or self._refresh_token
        if self._client_secret is None or refresh_token is None:
            raise LookupError(
                "Google Workspace directory credentials need attention. Reauthorise the connection."
            )
        async with httpx.AsyncClient(timeout=30) as client:
            token = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": config.client_id,
                    "client_secret": self._client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
            )
            _provider_response(token, "Google Workspace authorization failed")
            headers = {"Authorization": f"Bearer {token.json()['access_token']}"}
            courses = await _google_pages(
                client,
                "https://classroom.googleapis.com/v1/courses",
                headers,
                item_key="courses",
                params={"courseStates": "ACTIVE"},
            )
            students: dict[str, RosterAccount] = {}
            teachers: dict[str, RosterAccount] = {}
            for course in courses:
                course_id = str(course.get("id") or "")
                class_ref = course_id
                if not course_id or not class_ref:
                    continue
                for role, target, item_key in (
                    (UserRole.STUDENT, students, "students"),
                    (UserRole.TEACHER, teachers, "teachers"),
                ):
                    people = await _google_pages(
                        client,
                        f"https://classroom.googleapis.com/v1/courses/{course_id}/{item_key}",
                        headers,
                        item_key=item_key,
                    )
                    for item in people:
                        profile = item.get("profile") or {}
                        external_id = str(profile.get("id") or item.get("userId") or "")
                        email = str(profile.get("emailAddress") or "")
                        if not external_id or not email:
                            continue
                        existing = target.get(external_id)
                        class_ids = set(existing.class_external_ids) if existing else set()
                        class_ids.add(class_ref)
                        name = profile.get("name") or {}
                        target[external_id] = _roster_account(
                            external_id=external_id,
                            email=email,
                            first_name=_text(name.get("givenName")),
                            last_name=_text(name.get("familyName")),
                            role=role,
                            class_ids=class_ids,
                        )
        return RosterSyncBatch(
            students=tuple(students.values()),
            teachers=tuple(teachers.values()),
        )

    async def download_file(
        self,
        *,
        config: SsoSchoolConfig,
        file_id: str,
        drive_id: str | None = None,
    ) -> SsoCloudFile:
        del drive_id
        refresh_token = config.provider_credential or self._refresh_token
        if self._client_secret is None or refresh_token is None:
            raise LookupError("Google Drive credentials need attention")
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            token = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": config.client_id,
                    "client_secret": self._client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
            )
            _provider_response(token, "Google Drive authorization failed")
            headers = {"Authorization": f"Bearer {token.json()['access_token']}"}
            metadata = await client.get(
                f"https://www.googleapis.com/drive/v3/files/{file_id}",
                headers=headers,
                params={"fields": "id,name,mimeType,size"},
            )
            _provider_response(metadata, "Google Drive file was not found")
            body = metadata.json()
            mime_type = str(body.get("mimeType") or "application/octet-stream")
            if mime_type.startswith("application/vnd.google-apps"):
                download = await client.get(
                    f"https://www.googleapis.com/drive/v3/files/{file_id}/export",
                    headers=headers,
                    params={"mimeType": "application/pdf"},
                )
                filename = f"{body.get('name') or file_id}.pdf"
                mime_type = "application/pdf"
            else:
                download = await client.get(
                    f"https://www.googleapis.com/drive/v3/files/{file_id}",
                    headers=headers,
                    params={"alt": "media"},
                )
                filename = str(body.get("name") or f"drive-{file_id}")
            _provider_response(download, "Google Drive file download failed")
        return SsoCloudFile(
            filename=filename,
            content_type=mime_type,
            content=download.content,
        )


async def _microsoft_pages(
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
) -> AsyncIterator[dict[str, object]]:
    while url:
        response = await client.get(url, headers=headers)
        _provider_response(response, "Microsoft directory request failed")
        body = response.json()
        for item in body.get("value", []):
            if isinstance(item, dict):
                yield item
        url = str(body.get("@odata.nextLink") or "")


async def _google_pages(
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
    *,
    item_key: str,
    params: dict[str, str] | None = None,
) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    query = dict(params or {})
    while True:
        response = await client.get(url, headers=headers, params=query)
        _provider_response(response, "Google Workspace directory request failed")
        body = response.json()
        items.extend(item for item in body.get(item_key, []) if isinstance(item, dict))
        page_token = body.get("nextPageToken")
        if not page_token:
            return items
        query["pageToken"] = str(page_token)


def _provider_response(response: httpx.Response, message: str) -> None:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as error:
        raise LookupError(message) from error


def _roster_account(
    *,
    external_id: str,
    email: str,
    first_name: str | None,
    last_name: str | None,
    role: UserRole,
    class_ids: set[str],
) -> RosterAccount:
    return RosterAccount(
        external_id=external_id,
        email=email.casefold(),
        first_name=first_name,
        last_name=last_name,
        role=role,
        class_external_ids=tuple(sorted(class_ids)),
    )


def _text(value: object) -> str | None:
    return str(value) if value else None
