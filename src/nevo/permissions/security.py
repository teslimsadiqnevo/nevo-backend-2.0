import hashlib
import hmac
import secrets


class HmacInvitationTokenService:
    def __init__(self, session_pepper: str) -> None:
        self._key = session_pepper.encode()

    def issue(self) -> tuple[str, str]:
        token = secrets.token_urlsafe(32)
        return token, self.digest(token)

    def digest(self, token: str) -> str:
        return hmac.new(
            self._key,
            f"admin-invitation:{token}".encode(),
            hashlib.sha256,
        ).hexdigest()
