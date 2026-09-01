import time
from decimal import Decimal

from nevo.ai_gateway.agent import run_tool_loop
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
from nevo.ai_gateway.privacy import AiPrivacyGuard
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
        cache_write_cost_usd_per_million: Decimal,
        cache_read_cost_usd_per_million: Decimal,
        privacy: AiPrivacyGuard | None = None,
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
        self._cache_write_cost = cache_write_cost_usd_per_million
        self._cache_read_cost = cache_read_cost_usd_per_million
        self._privacy = privacy or AiPrivacyGuard()

    @property
    def configured(self) -> bool:
        """Whether a real provider can be reached.

        False means every request will answer from the rule-based fallback,
        which reads as a poor model rather than as missing configuration.
        """
        return bool(getattr(self._provider, "configured", False))

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
        safe_variables = self._privacy.sanitize_variables(
            request.variables,
            requester_user_id=request.requester_user_id,
            student_id=request.student_id,
            sensitive_terms=context.sensitive_terms,
        )
        rendered = self._renderer.render(template, safe_variables)
        priority = SERVICE_PRIORITIES[request.service]
        started = time.perf_counter()
        responses: list[ProviderResponse] = []
        compliance_retries = 0
        error_code: str | None = None
        accepted: ProviderResponse | None = None
        user_content = rendered.user_content

        for attempt in range(self._max_compliance_retries + 1):
            provider_request = ProviderRequest(
                system_instruction=self._privacy.sanitize_text(
                    rendered.system_instruction,
                    pseudonym=self._privacy.pseudonym(
                        request.student_id or request.requester_user_id
                    ),
                    sensitive_terms=context.sensitive_terms,
                ),
                user_content=self._privacy.sanitize_text(
                    user_content,
                    pseudonym=self._privacy.pseudonym(
                        request.student_id or request.requester_user_id
                    ),
                    sensitive_terms=context.sensitive_terms,
                ),
                max_output_tokens=request.max_output_tokens,
                model=request.model,
                cache_prompt=request.cache_prompt,
                tools=request.tools,
            )

            async def generate_once(
                provider_request: ProviderRequest = provider_request,
            ) -> ProviderResponse:
                if provider_request.tools and request.tool_executor is not None:
                    outcome = await run_tool_loop(
                        provider=self._provider,
                        request=provider_request,
                        execute=request.tool_executor,
                    )
                    return outcome.response_with_text()
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
        cache_creation_input_tokens = sum(item.cache_creation_input_tokens for item in responses)
        cache_read_input_tokens = sum(item.cache_read_input_tokens for item in responses)
        estimated_cost = self._estimated_cost(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            thought_tokens=thought_tokens,
            cache_creation_input_tokens=cache_creation_input_tokens,
            cache_read_input_tokens=cache_read_input_tokens,
        )
        call_id = await self._calls.record(
            AiCallAudit(
                context=context,
                template_id=template.id,
                service=request.service,
                priority=priority,
                provider=accepted.provider,
                model=accepted.model,
                status=(AiCallStatus.FALLBACK if fallback_used else AiCallStatus.SUCCEEDED),
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
        cache_creation_input_tokens: int,
        cache_read_input_tokens: int,
    ) -> Decimal:
        return (
            Decimal(input_tokens) * self._input_cost
            + Decimal(output_tokens + thought_tokens) * self._output_cost
            + Decimal(cache_creation_input_tokens) * self._cache_write_cost
            + Decimal(cache_read_input_tokens) * self._cache_read_cost
        ) / ONE_MILLION


def public_ai_error(error: Exception) -> AiGatewayError:
    if isinstance(error, AiGatewayError):
        return error
    return AiGatewayError()
