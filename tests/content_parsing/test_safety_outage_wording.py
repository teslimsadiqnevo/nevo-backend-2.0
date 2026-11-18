from nevo.content_parsing.failures import failure_reason


def test_checker_outage_is_described_as_temporary_not_unsafe_material():
    message = failure_reason("SafetyUnavailable: provider request failed")
    assert "could not run" in message
    assert "Nothing is wrong with your file" in message
    assert "held this file back" not in message
