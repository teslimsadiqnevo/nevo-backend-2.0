"""Server-side privacy guard tests."""
from uuid import UUID

from nevo.ai_gateway.privacy import AiPrivacyGuard

SUBJECT = UUID("11111111-1111-1111-1111-111111111111")
GUARD = AiPrivacyGuard()
PSEUDONYM = AiPrivacyGuard.pseudonym(SUBJECT)


def sanitize(text: str, *, terms: tuple[str, ...] = ()) -> str:
    return GUARD.sanitize_text(text, pseudonym=PSEUDONYM, sensitive_terms=terms)


def test_pseudonym_is_stable_and_opaque() -> None:
    assert AiPrivacyGuard.pseudonym(SUBJECT) == PSEUDONYM
    assert str(SUBJECT) not in PSEUDONYM
    assert PSEUDONYM.startswith("Learner-")


def test_emails_and_phone_numbers_are_stripped() -> None:
    result = sanitize("Reach ada@example.com or +2348012345678 today.")

    assert "ada@example.com" not in result
    assert "+2348012345678" not in result
    assert "[email removed]" in result
    assert "[contact removed]" in result


def test_credentials_are_stripped() -> None:
    result = sanitize("password: hunter2 and api_key: sk-abc123")

    assert "hunter2" not in result
    assert "sk-abc123" not in result


def test_labelled_identifier_is_replaced_with_the_pseudonym() -> None:
    result = sanitize("Student name: Ada Lovelace")

    assert "Ada Lovelace" not in result
    assert PSEUDONYM in result


def test_labelled_identifier_stops_at_the_sentence_boundary() -> None:
    """A greedy match here used to swallow the rest of the lesson text."""
    result = sanitize("Student name: Ada Lovelace. Half of eight is four.")

    assert "Ada Lovelace" not in result
    assert "Half of eight is four." in result


def test_labelled_identifier_stops_at_a_clause_boundary() -> None:
    result = sanitize("name: Ada Lovelace, who scored 8 out of 10")

    assert "Ada Lovelace" not in result
    assert "who scored 8 out of 10" in result


def test_known_names_are_redacted_from_free_prose() -> None:
    result = sanitize(
        "Ada struggled with fractions but Ada Lovelace improved after the break.",
        terms=("Ada", "Ada Lovelace"),
    )

    assert "Ada" not in result
    assert "Lovelace" not in result
    assert "struggled with fractions" in result


def test_longer_names_win_over_their_prefixes() -> None:
    result = sanitize("Ada Lovelace did well.", terms=("Ada", "Ada Lovelace"))

    assert result == f"{PSEUDONYM} did well."


def test_name_redaction_respects_word_boundaries() -> None:
    result = sanitize("Adaptation improved for Ada.", terms=("Ada",))

    assert "Adaptation improved" in result
    assert result.endswith(f"for {PSEUDONYM}.")


def test_short_terms_are_ignored_to_avoid_shredding_prose() -> None:
    result = sanitize("Al ran a lap.", terms=("Al",))

    assert result == "Al ran a lap."


def test_sensitive_variables_are_replaced_wholesale() -> None:
    sanitized = GUARD.sanitize_variables(
        {
            "student_name": "Ada Lovelace",
            "email": "ada@example.com",
            "age_band": "7-9",
            "observation": "Ada solved six of eight problems.",
        },
        requester_user_id=SUBJECT,
        student_id=None,
        sensitive_terms=("Ada",),
    )

    assert sanitized["student_name"] == PSEUDONYM
    assert sanitized["email"] == PSEUDONYM
    assert sanitized["age_band"] == "7-9"
    assert "Ada" not in sanitized["observation"]
    assert "six of eight problems" in sanitized["observation"]
