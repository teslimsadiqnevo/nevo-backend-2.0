from nevo.ai_gateway.compliance import ZeroTagCompliancePolicy
from nevo.ai_gateway.entities import (
    AiGenerationRequest,
    ProviderResponse,
)
from nevo.domain.ai_gateway.vocabulary import AiProviderName


class RuleBasedFallbackGenerator:
    def __init__(self, compliance: ZeroTagCompliancePolicy) -> None:
        self._compliance = compliance

    def generate(
        self,
        request: AiGenerationRequest,
        *,
        user_content: str,
    ) -> ProviderResponse:
        source = (
            request.variables.get("source_text")
            or request.variables.get("content")
            or request.variables.get("text")
            or user_content
        ).strip()
        safe_source = self._compliance.sanitize(source)
        if not safe_source:
            safe_source = (
                "Continue with the original learning activity. "
                "Your teacher's source material remains available."
            )
        return ProviderResponse(
            text=safe_source,
            provider=AiProviderName.RULE_BASED,
            model="deterministic-v1",
        )
