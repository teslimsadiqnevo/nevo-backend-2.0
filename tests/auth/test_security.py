from nevo.auth.security import Argon2idCredentialHasher, HmacTokenService

PEPPER_A = "a" * 32
PEPPER_B = "b" * 32
PEPPER_C = "c" * 32


def test_password_and_pin_hashes_are_argon2id_and_independently_peppered() -> None:
    hasher = Argon2idCredentialHasher(
        PEPPER_A,
        PEPPER_B,
        time_cost=1,
        memory_cost=8_192,
        parallelism=1,
    )

    password_hash = hasher.hash_password("correct horse battery staple")
    pin_hash = hasher.hash_pin("2443")

    assert password_hash.startswith("$argon2id$")
    assert pin_hash.startswith("$argon2id$")
    assert "correct horse battery staple" not in password_hash
    assert "2443" not in pin_hash
    assert hasher.verify_password(password_hash, "correct horse battery staple")
    assert not hasher.verify_password(password_hash, "wrong password")
    assert hasher.verify_pin(pin_hash, "2443")
    assert not hasher.verify_pin(pin_hash, "0000")


def test_missing_hash_still_performs_verification_and_returns_false() -> None:
    hasher = Argon2idCredentialHasher(
        PEPPER_A,
        PEPPER_B,
        time_cost=1,
        memory_cost=8_192,
        parallelism=1,
    )

    assert not hasher.verify_password(None, "some password")
    assert not hasher.verify_pin(None, "2443")


def test_session_tokens_are_random_and_only_digests_are_stable() -> None:
    tokens = HmacTokenService(PEPPER_C)

    first_token, first_digest = tokens.issue()
    second_token, second_digest = tokens.issue()

    assert first_token != second_token
    assert first_digest != second_digest
    assert first_token not in first_digest
    assert tokens.digest(first_token) == first_digest
    assert len(first_digest) == 64
