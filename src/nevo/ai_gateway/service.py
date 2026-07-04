import time
from decimal import Decimal

from nevo.ai_gateway.compliance import (
    ZERO_TAG_REWRITE_INSTRUCTION,
    ZeroTagCompliancePolicy,
)
from nevo.ai_gateway.entities import (
    AiCallAudit,
    AiGenerationRequest,
    AiGenerationResult,
    ProviderRequest,
    ProviderResponse,
)
from nevo.ai_gateway.errors import (
    AiGatewayError,
    PromptTemplateNotFoundError,
    ProviderResponseError,
    ProviderUnavailableError,
)
from nevo.ai_gateway.ports import (
    AiCallRepository,
    FallbackGenerator,
    PromptTemplateRepository,
    RequestScheduler,
    TextGenerationProvider,
)
from nevo.ai_gateway.prompts import PromptRenderer
from nevo.domain.ai_gateway.vocabulary import (
    SERVICE_PRIORITIES,
    AiCallStatus,
)

ONE_MILLION = Decimal("1000000")


class AiGatewayService:
    def __init__(
        self,
        *,
        prompts: PromptTemplateRepository,
        calls: AiCallRepository,
        provider: TextGenerationProvider,
        fallback: FallbackGenerator,
        scheduler: RequestScheduler,
        compliance: ZeroTagCompliancePolicy,
        renderer: PromptRenderer,
        max_compliance_retries: int,
        input_cost_usd_per_million: Decimal,
        output_cost_usd_per_million: Decimal,
    ) -> None:
        self._prompts = prompts
        self._calls = calls
        self._provider = provider
        self._fallback = fallback
        self._scheduler = scheduler
        self._compliance = compliance
        self._renderer = renderer
        self._max_compliance_retries = max_compliance_retries
        self._input_cost = input_cost_usd_per_million
        self._output_cost = output_cost_usd_per_million

    async def generate(
        self,
        request: AiGenerationRequest,
    ) -> AiGenerationResult:
        context = await self._calls.resolve_context(
            requester_user_id=request.requester_user_id,
            student_id=request.student_id,
        )
        template = await self._prompts.active(
            name=request.prompt_name,
            service=request.service,
        )
        if template is None:
            raise PromptTemplateNotFoundError
        rendered = self._renderer.render(template, request.variables)
        priority = SERVICE_PRIORITIES[request.service]
        started = time.perf_counter()
        responses: list[ProviderResponse] = []
        compliance_retries = 0
        error_code: str | None = None
        accepted: ProviderResponse | None = None
        user_content = rendered.user_content

        for attempt in range(self._max_compliance_retries + 1):
            provider_request = ProviderRequest(
                system_instruction=rendered.system_instruction,
                user_content=user_content,
                max_output_tokens=request.max_output_tokens,
            )

            async def generate_once(
                provider_request: ProviderRequest = provider_request,
            ) -> ProviderResponse:
                return await self._provider.generate(provider_request)

            try:
                response = await self._scheduler.execute(
                    priority,
                    generate_once,
                )
            except (ProviderUnavailableError, ProviderResponseError) as error:
                error_code = error.code
                break
            responses.append(response)
            compliance = self._compliance.inspect(response.text)
            if compliance.allowed:
                accepted = response
                break
            error_code = "zero_tag_rejected"
            if attempt < self._max_compliance_retries:
                compliance_retries += 1
                user_content += ZERO_TAG_REWRITE_INSTRUCTION

        fallback_used = accepted is None
        if accepted is None:
            accepted = self._fallback.generate(
                request,
                user_content=rendered.user_content,
            )
        latency_ms = max(0, round((time.perf_counter() - started) * 1_000))
        input_tokens = sum(item.input_tokens for item in responses)
        output_tokens = sum(item.output_tokens for item in responses)
        thought_tokens = sum(item.thought_tokens for item in responses)
        estimated_cost = self._estimated_cost(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            thought_tokens=thought_tokens,
        )
        call_id = await self._calls.record(
            AiCallAudit(
                context=context,
                template_id=template.id,
                service=request.service,
                priority=priority,
                provider=accepted.provider,
                model=accepted.model,
                status=(
                    AiCallStatus.FALLBACK
                    if fallback_used
                    else AiCallStatus.SUCCEEDED
                ),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                thought_tokens=thought_tokens,
                latency_ms=latency_ms,
                estimated_cost_usd=estimated_cost,
                compliance_retries=compliance_retries,
                fallback_used=fallback_used,
                error_code=error_code,
            )
        )
        return AiGenerationResult(
            text=accepted.text,
            provider=accepted.provider,
            model=accepted.model,
            prompt_name=template.name,
            prompt_version=template.version,
            fallback_used=fallback_used,
            compliance_retries=compliance_retries,
            call_id=call_id,
        )

    async def close(self) -> None:
        await self._scheduler.close()
        await self._provider.close()

    def _estimated_cost(
        self,
        *,
        input_tokens: int,
        output_tokens: int,
        thought_tokens: int,
    ) -> Decimal:
        return (
            Decimal(input_tokens) * self._input_cost
            + Decimal(output_tokens + thought_tokens) * self._output_cost
        ) / ONE_MILLION


def public_ai_error(error: Exception) -> AiGatewayError:
    if isinstance(error, AiGatewayError):
        return error
    return AiGatewayError()
