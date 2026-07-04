import re

from nevo.ai_gateway.entities import ComplianceResult
from nevo.domain.learner_profiles.vocabulary import PROHIBITED_SCHEMA_TERMS

PROHIBITED_RESPONSE_TERMS = PROHIBITED_SCHEMA_TERMS | frozenset(
    {
        "clinical",
        "diagnosed",
        "diagnoses",
        "impairment",
        "pathology",
        "patient",
        "syndrome",
        "treatment",
    }
)


class ZeroTagCompliancePolicy:
    def __init__(self) -> None:
        self._patterns = {
            term: re.compile(
                rf"(?<!\w){
                    r'[\s_-]+'.join(
                        re.escape(part) for part in term.split('_')
                    )
                }(?!\w)",
                re.IGNORECASE,
            )
            for term in PROHIBITED_RESPONSE_TERMS
        }

    def inspect(self, text: str) -> ComplianceResult:
        violations = frozenset(
            term
            for term, pattern in self._patterns.items()
            if pattern.search(text)
        )
        return ComplianceResult(
            allowed=not violations,
            violations=violations,
        )

    def sanitize(self, text: str) -> str:
        sanitized = text
        for pattern in self._patterns.values():
            sanitized = pattern.sub("observable learning need", sanitized)
        return sanitized


ZERO_TAG_REWRITE_INSTRUCTION = (
    "\n\nYour previous response violated Nevo's Zero-Tag policy. Rewrite it "
    "using only observable learning preferences, classroom behavior, and "
    "functional support. Do not mention or infer labels."
)
