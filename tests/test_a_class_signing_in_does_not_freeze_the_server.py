"""Signing in must not stop every other request in the process.

Argon2id is meant to be expensive, and it is synchronous C code. Called
directly from an async handler it holds the event loop for its whole
duration, so nothing else in the process runs - not another sign-in, not a
lesson read, not the health check Render uses to decide the service is alive.

Measured on this machine before the change: twenty concurrent sign-ins held
the loop for 1466 ms and let four other turns through. After: 765 ms, and 140
other turns. On a shared-vCPU instance both numbers are several times larger,
which is what "the test sign-ins hang" looked like from outside.

These tests assert the property - the loop keeps serving - rather than the
mechanism, so a different way of getting the work off the loop still passes.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from nevo.auth.security import HASH_CONCURRENCY, Argon2idCredentialHasher


@pytest.fixture(scope="module")
def hasher() -> Argon2idCredentialHasher:
    return Argon2idCredentialHasher("p" * 32, "q" * 32)


@pytest.fixture(scope="module")
def pin_hash(hasher: Argon2idCredentialHasher) -> str:
    return hasher.hash_pin("4821")


async def _turns_served_during(work) -> tuple[int, float]:
    """How many times the loop got back to other work while `work` ran."""
    turns = 0
    stop = False

    async def heartbeat() -> None:
        nonlocal turns
        while not stop:
            turns += 1
            await asyncio.sleep(0.005)

    beat = asyncio.create_task(heartbeat())
    await asyncio.sleep(0.02)
    started = time.perf_counter()
    await work()
    elapsed = time.perf_counter() - started
    stop = True
    beat.cancel()
    return turns, elapsed


@pytest.mark.asyncio
async def test_a_class_signing_in_leaves_the_loop_serving(hasher, pin_hash) -> None:
    async def twenty_children() -> None:
        await asyncio.gather(*(hasher.verify_pin_async(pin_hash, "4821") for _ in range(20)))

    turns, elapsed = await _turns_served_during(twenty_children)

    # Generous, because CI machines vary. The failure this guards against is
    # a frozen loop, which serves single digits however fast the box is.
    assert turns > 20, (
        f"the loop served only {turns} other turns in {elapsed * 1000:.0f} ms of "
        "sign-ins, which means hashing is back on the event loop"
    )


@pytest.mark.asyncio
async def test_the_same_holds_for_passwords(hasher) -> None:
    password_hash = await hasher.hash_password_async("a-long-enough-password")

    async def ten_teachers() -> None:
        await asyncio.gather(
            *(
                hasher.verify_password_async(password_hash, "a-long-enough-password")
                for _ in range(10)
            )
        )

    turns, _ = await _turns_served_during(ten_teachers)
    assert turns > 10


@pytest.mark.asyncio
async def test_setting_a_pin_does_not_freeze_the_loop_either(hasher) -> None:
    """A whole class being onboarded at once writes PINs, it does not read them."""

    async def ten_children() -> None:
        await asyncio.gather(*(hasher.hash_pin_async("4821") for _ in range(10)))

    turns, _ = await _turns_served_during(ten_children)
    assert turns > 10


@pytest.mark.asyncio
async def test_concurrency_is_bounded_so_memory_cannot_run_away(hasher, pin_hash) -> None:
    """Unbounded is the other failure mode.

    Each call allocates 64 MiB. Letting the default executor run as many as it
    likes would risk an out-of-memory restart on a small instance, which is
    worse than a queue.
    """
    live = 0
    peak = 0
    original = hasher.verify_pin

    def counted(*args):
        nonlocal live, peak
        live += 1
        peak = max(peak, live)
        try:
            return original(*args)
        finally:
            live -= 1

    hasher.verify_pin = counted  # type: ignore[method-assign]
    try:
        await asyncio.gather(*(hasher.verify_pin_async(pin_hash, "4821") for _ in range(12)))
    finally:
        del hasher.verify_pin

    assert peak <= HASH_CONCURRENCY, f"{peak} hashes ran at once, limit is {HASH_CONCURRENCY}"


@pytest.mark.asyncio
async def test_the_answers_are_the_same_as_the_blocking_form(hasher, pin_hash) -> None:
    """Moving work off the loop must not change what it decides."""
    assert await hasher.verify_pin_async(pin_hash, "4821") is True
    assert await hasher.verify_pin_async(pin_hash, "0000") is False
    assert await hasher.verify_pin_async(None, "4821") is False

    fresh = await hasher.hash_pin_async("1234")
    assert await hasher.verify_pin_async(fresh, "1234") is True
    assert await hasher.verify_pin_async(fresh, "4321") is False


@pytest.mark.asyncio
async def test_a_wrong_pin_costs_the_same_work_as_a_right_one(hasher, pin_hash) -> None:
    """The constant-work property the dummy hash exists for, still intact.

    A missing user must not be cheaper to check than a present one, or the
    timing tells an attacker which login identifiers exist.
    """
    samples = []
    for args in ((pin_hash, "4821"), (pin_hash, "0000"), (None, "4821")):
        started = time.perf_counter()
        await hasher.verify_pin_async(*args)
        samples.append(time.perf_counter() - started)

    assert min(samples) > 0
    assert max(samples) / min(samples) < 4, f"timings diverge too far: {samples}"


def test_the_hasher_is_reusable_across_event_loops(hasher, pin_hash) -> None:
    """The gate belongs to a loop; the hasher outlives any one of them.

    The application builds one hasher at start-up and keeps it. Tests run many
    loops through the same object, and a semaphore bound to a dead loop would
    fail on the next one.
    """
    for _ in range(3):
        assert asyncio.run(hasher.verify_pin_async(pin_hash, "4821")) is True


def test_the_blocking_forms_still_work_for_scripts_and_seeds(hasher) -> None:
    """Seed scripts have no loop to block, and still need to set a PIN."""
    written = hasher.hash_pin("4821")
    assert hasher.verify_pin(written, "4821") is True
    assert hasher.verify_pin(written, "0000") is False
