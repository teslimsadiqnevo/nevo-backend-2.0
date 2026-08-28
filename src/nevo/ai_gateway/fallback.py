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
        del user_content
        source = (
            request.variables.get("source_text")
            or request.variables.get("content")
            or request.variables.get("text")
            or ""
        ).strip()
        safe_source = self._compliance.sanitize(source)
        if request.prompt_name.startswith("ask_nevo."):
            safe_source = (
                "I can help with this, but I need the live assistant connection "
                "to give a specific answer. Try the current lesson example first, "
                "then use one small check-in question to decide the next step."
            )
        elif not safe_source:
            safe_source = (
                "Continue with the original learning activity. "
                "Your teacher's source material remains available."
            )
        return ProviderResponse(
            text=safe_source,
            provider=AiProviderName.RULE_BASED,
            model="deterministic-v1",
        )
