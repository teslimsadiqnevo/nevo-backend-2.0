from nevo.permissions.security import HmacInvitationTokenService


def test_invitation_tokens_are_random_and_only_digest_is_stable() -> None:
    service = HmacInvitationTokenService(
        "session-pepper-that-is-longer-than-thirty-two-characters"
    )

    first_token, first_digest = service.issue()
    second_token, second_digest = service.issue()

    assert first_token != second_token
    assert first_digest != second_digest
    assert service.digest(first_token) == first_digest
    assert len(first_digest) == 64
    assert first_token not in first_digest
