from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from uuid import UUID

EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
PHONE_PATTERN = re.compile(r"(?<!\w)(?:\+?\d[\d ()-]{7,}\d)(?!\w)")
CREDENTIAL_PATTERN = re.compile(
    r"(?i)\b(password|passcode|pin|api[_ -]?key|access[_ -]?token|refresh[_ -]?token)\b"
    r"\s*[:=]\s*[^\s,;]+"
)
# The value stops at a sentence or clause boundary. Running past a full stop
# would swallow the rest of the lesson text along with the identifier.
LABELLED_IDENTIFIER_PATTERN = re.compile(
    r"(?i)\b(student|teacher|parent|guardian|school|name|age)\s*[:=]\s*([^\n,;.]{1,60})"
)
SENSITIVE_KEYS = {
    "email",
    "first_name",
    "firstname",
    "last_name",
    "lastname",
    "full_name",
    "student_name",
    "teacher_name",
    "school_name",
    "age",
    "date_of_birth",
    "dob",
    "password",
    "pin",
    "credential",
    "token",
}


class AiPrivacyGuard:
    """Pseudonymise direct identifiers before any provider receives a prompt."""

    def sanitize_variables(
        self,
        variables: Mapping[str, str],
        *,
        requester_user_id: UUID,
        student_id: UUID | None,
        sensitive_terms: tuple[str, ...] = (),
    ) -> dict[str, str]:
        subject = student_id or requester_user_id
        pseudonym = self.pseudonym(subject)
        sanitized: dict[str, str] = {}
        for key, value in variables.items():
            normalized = key.casefold().replace("-", "_")
            if normalized in SENSITIVE_KEYS or any(
                marker in normalized
                for marker in ("email", "password", "credential", "api_key", "token")
            ):
                sanitized[key] = pseudonym
            elif normalized.endswith("_name") or normalized.startswith("name_"):
                sanitized[key] = pseudonym
            elif normalized in {"age_band", "year_group"}:
                sanitized[key] = value
            else:
                sanitized[key] = self.sanitize_text(
                    value,
                    pseudonym=pseudonym,
                    sensitive_terms=sensitive_terms,
                )
        return sanitized

    def sanitize_text(
        self,
        value: str,
        *,
        pseudonym: str,
        sensitive_terms: tuple[str, ...] = (),
    ) -> str:
        value = EMAIL_PATTERN.sub("[email removed]", value)
        value = PHONE_PATTERN.sub("[contact removed]", value)
        value = CREDENTIAL_PATTERN.sub(lambda match: f"{match.group(1)}: [removed]", value)
        value = LABELLED_IDENTIFIER_PATTERN.sub(
            lambda match: f"{match.group(1)}: {pseudonym}", value
        )
        terms = sorted(
            {term.strip() for term in sensitive_terms if len(term.strip()) >= 3},
            key=len,
            reverse=True,
        )
        if not terms:
            return value
        pattern = re.compile(
            r"(?<!\w)(?:" + "|".join(re.escape(term) for term in terms) + r")(?!\w)",
            re.IGNORECASE,
        )
        return pattern.sub(pseudonym, value)

    @staticmethod
    def pseudonym(subject_id: UUID) -> str:
        digest = hashlib.sha256(subject_id.bytes).hexdigest()[:10].upper()
        return f"Learner-{digest}"
