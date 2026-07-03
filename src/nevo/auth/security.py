import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from argon2.low_level import Type


class Argon2idCredentialHasher:
    def __init__(
        self,
        password_pepper: str,
        pin_pepper: str,
        *,
        time_cost: int = 3,
        memory_cost: int = 65_536,
        parallelism: int = 2,
    ) -> None:
        self._password_pepper = password_pepper.encode()
        self._pin_pepper = pin_pepper.encode()
        self._hasher = PasswordHasher(
            time_cost=time_cost,
            memory_cost=memory_cost,
            parallelism=parallelism,
            hash_len=32,
            salt_len=16,
            type=Type.ID,
        )
        self._dummy_password_hash = self.hash_password(
            "constant-work-placeholder-password"
        )
        self._dummy_pin_hash = self.hash_pin("000000")

    @staticmethod
    def _peppered(secret: str, pepper: bytes) -> str:
        return hmac.new(pepper, secret.encode(), hashlib.sha256).hexdigest()

    def hash_password(self, password: str) -> str:
        return self._hasher.hash(self._peppered(password, self._password_pepper))

    def verify_password(self, password_hash: str | None, password: str) -> bool:
        return self._verify(
            password_hash or self._dummy_password_hash,
            self._peppered(password, self._password_pepper),
        ) and password_hash is not None

    def hash_pin(self, pin: str) -> str:
        return self._hasher.hash(self._peppered(pin, self._pin_pepper))

    def verify_pin(self, pin_hash: str | None, pin: str) -> bool:
        return self._verify(
            pin_hash or self._dummy_pin_hash,
            self._peppered(pin, self._pin_pepper),
        ) and pin_hash is not None

    def _verify(self, secret_hash: str, prepared_secret: str) -> bool:
        try:
            return self._hasher.verify(secret_hash, prepared_secret)
        except (InvalidHashError, VerificationError, VerifyMismatchError):
            return False


class HmacTokenService:
    def __init__(self, session_pepper: str) -> None:
        self._pepper = session_pepper.encode()

    def issue(self) -> tuple[str, str]:
        token = secrets.token_urlsafe(32)
        return token, self.digest(token)

    def digest(self, token: str) -> str:
        return self._hmac(f"session:{token}")

    def protect_identifier(self, value: str) -> str:
        return self._hmac(f"identifier:{value.casefold().strip()}")

    def _hmac(self, value: str) -> str:
        return hmac.new(
            self._pepper,
            value.encode(),
            hashlib.sha256,
        ).hexdigest()
