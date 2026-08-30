from cryptography.fernet import Fernet, InvalidToken


class SsoCredentialCipher:
    def __init__(self, key: str | None) -> None:
        self._fernet = Fernet(key.encode("ascii")) if key else None

    def encrypt(self, value: str) -> str:
        if self._fernet is None:
            raise LookupError("SSO credential encryption is not configured")
        return self._fernet.encrypt(value.encode("utf-8")).decode("ascii")

    def decrypt(self, value: str) -> str:
        if self._fernet is None:
            raise LookupError("SSO credential encryption is not configured")
        try:
            return self._fernet.decrypt(value.encode("ascii")).decode("utf-8")
        except InvalidToken as error:
            raise LookupError("Stored SSO credentials need attention") from error
