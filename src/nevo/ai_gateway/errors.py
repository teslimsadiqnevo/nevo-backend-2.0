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
    code = "provider_unavailable"


class ProviderResponseError(AiGatewayError):
    code = "provider_response_invalid"


class SchedulerClosedError(AiGatewayError):
    code = "scheduler_closed"
