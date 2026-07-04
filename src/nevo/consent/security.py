import hashlib
import hmac
import secrets


class HmacConsentTokenService:
    def __init__(self, pepper: str) -> None:
        self._key = pepper.encode()

    def issue(self) -> tuple[str, str]:
        token = secrets.token_urlsafe(32)
        return token, self.digest(token)

    def digest(self, token: str) -> str:
        return hmac.new(
            self._key,
            f"parent-consent:{token}".encode(),
            hashlib.sha256,
        ).hexdigest()
