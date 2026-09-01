class AiGatewayError(Exception):
    code = "ai_gateway_error"
    public_message = "AI generation is temporarily unavailable."


class PromptTemplateNotFoundError(AiGatewayError):
    code = "prompt_template_not_found"
    public_message = "The requested AI prompt is not configured."


class PromptVariablesError(AiGatewayError):
    code = "invalid_prompt_variables"
    public_message = "Required prompt information is missing."


class InvalidAiContextError(AiGatewayError):
    code = "invalid_ai_context"
    public_message = "The AI request is outside your school context."


class ProviderUnavailableError(AiGatewayError):
    """The provider was called but the call did not succeed."""

    code = "provider_unavailable"


class ProviderNotConfiguredError(ProviderUnavailableError):
    """No API key, so no request was ever made.

    Distinct from ProviderUnavailableError because the two need completely
    different responses: this is a deployment setting, not an outage. While
    they shared one code, a missing key was indistinguishable from a provider
    failure in the audit trail, and the only symptom a user saw was a generic
    fallback answer that looked like a bad model.
    """

    code = "provider_not_configured"
    public_message = "The AI provider is not configured."


class ProviderResponseError(AiGatewayError):
    code = "provider_response_invalid"


class SchedulerClosedError(AiGatewayError):
    code = "scheduler_closed"
