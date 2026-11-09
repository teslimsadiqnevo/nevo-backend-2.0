import asyncio
import hashlib
import hmac
import os
import secrets
import weakref

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from argon2.low_level import Type

#: How many credentials may be hashed at the same time.
#:
#: Argon2id is meant to be expensive, and at 64 MiB per call that cost is
#: memory as well as processor. The event loop runs one request at a time, so
#: a verify on the loop stops everything else in the process for as long as it
#: takes - a class of children signing in together stalled health checks and
#: lesson reads behind them, which is what a sign-in "hanging" looked like.
#:
#: The work is handed to threads instead, and bounded, because unbounded is
#: the other failure: the default executor would allow several 64 MiB
#: allocations at once on an instance that does not have that to spare, and an
#: out-of-memory restart is worse than a queue. Argon2 releases the GIL, so
#: these threads do run in parallel.
HASH_CONCURRENCY = max(1, int(os.environ.get("AUTH_HASH_CONCURRENCY", "2")))


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
        self._dummy_password_hash = self.hash_password("constant-work-placeholder-password")
        self._dummy_pin_hash = self.hash_pin("000000")
        #: Keyed by event loop; see the _gate property.
        self._gates: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()

    @staticmethod
    def _peppered(secret: str, pepper: bytes) -> str:
        return hmac.new(pepper, secret.encode(), hashlib.sha256).hexdigest()

    def hash_password(self, password: str) -> str:
        return self._hasher.hash(self._peppered(password, self._password_pepper))

    def verify_password(self, password_hash: str | None, password: str) -> bool:
        return (
            self._verify(
                password_hash or self._dummy_password_hash,
                self._peppered(password, self._password_pepper),
            )
            and password_hash is not None
        )

    def hash_pin(self, pin: str) -> str:
        return self._hasher.hash(self._peppered(pin, self._pin_pepper))

    def verify_pin(self, pin_hash: str | None, pin: str) -> bool:
        return (
            self._verify(
                pin_hash or self._dummy_pin_hash,
                self._peppered(pin, self._pin_pepper),
            )
            and pin_hash is not None
        )

    def _verify(self, secret_hash: str, prepared_secret: str) -> bool:
        try:
            return self._hasher.verify(secret_hash, prepared_secret)
        except (InvalidHashError, VerificationError, VerifyMismatchError):
            return False

    # The async forms below are what a request handler must use. They do the
    # same work off the event loop, so one sign-in cannot hold up every other
    # request in the process. The sync forms remain for scripts, seeds and
    # tests, where there is no loop to block.

    @property
    def _gate(self) -> asyncio.Semaphore:
        """One semaphore per running loop, created on first use.

        Not built in __init__ because the hasher is constructed during
        application start-up and reused, while a semaphore belongs to the loop
        it is awaited on - tests run several loops through the same hasher.
        """
        loop = asyncio.get_running_loop()
        gate = self._gates.get(loop)
        if gate is None:
            gate = asyncio.Semaphore(HASH_CONCURRENCY)
            self._gates[loop] = gate
        return gate

    async def _off_the_loop(self, work, *args):
        async with self._gate:
            return await asyncio.to_thread(work, *args)

    async def verify_password_async(self, password_hash: str | None, password: str) -> bool:
        return await self._off_the_loop(self.verify_password, password_hash, password)

    async def verify_pin_async(self, pin_hash: str | None, pin: str) -> bool:
        return await self._off_the_loop(self.verify_pin, pin_hash, pin)

    async def hash_password_async(self, password: str) -> str:
        return await self._off_the_loop(self.hash_password, password)

    async def hash_pin_async(self, pin: str) -> str:
        return await self._off_the_loop(self.hash_pin, pin)


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
