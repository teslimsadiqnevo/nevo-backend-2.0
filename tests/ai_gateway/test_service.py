from decimal import Decimal
from uuid import uuid4

import pytest

from nevo.ai_gateway.compliance import ZeroTagCompliancePolicy
from nevo.ai_gateway.entities import (
    AiGenerationRequest,
    AiRequestContext,
    PromptTemplate,
    ProviderResponse,
)
from nevo.ai_gateway.errors import (
    PromptTemplateNotFoundError,
    PromptVariablesError,
    ProviderUnavailableError,
)
from nevo.ai_gateway.fallback import RuleBasedFallbackGenerator
from nevo.ai_gateway.prompts import PromptRenderer
from nevo.ai_gateway.service import AiGatewayService
from nevo.domain.ai_gateway.vocabulary import (
    AiCallStatus,
    AiPriority,
    AiProviderName,
    AiService,
)

from .fakes import (
    ImmediateScheduler,
    MemoryCallRepository,
    MemoryPromptRepository,
    SequenceProvider,
)


def template() -> PromptTemplate:
    return PromptTemplate(
        id=uuid4(),
        service=AiService.ADAPTATION,
        name="adaptation.default",
        version=3,
        system_template="Use only the teacher source.",
        user_template="{source_text}\nRequest: {instruction}",
        required_variables=frozenset({"source_text", "instruction"}),
    )


def request() -> AiGenerationRequest:
    return AiGenerationRequest(
        requester_user_id=uuid4(),
        student_id=uuid4(),
        service=AiService.ADAPTATION,
        prompt_name="adaptation.default",
        variables={
            "source_text": "Plants use light to make food.",
            "instruction": "Use shorter sentences.",
        },
    )


def provider_response(
    text: str,
    *,
    input_tokens: int = 10,
    output_tokens: int = 5,
    thought_tokens: int = 0,
) -> ProviderResponse:
    return ProviderResponse(
        text=text,
        provider=AiProviderName.GEMINI,
        model="gemini-test",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        thought_tokens=thought_tokens,
    )


def service_with(
    provider: SequenceProvider,
    *,
    include_template: bool = True,
    max_retries: int = 2,
) -> tuple[AiGatewayService, MemoryCallRepository, ImmediateScheduler]:
    calls = MemoryCallRepository(
        AiRequestContext(
            requester_user_id=uuid4(),
            school_id=uuid4(),
            student_id=None,
        )
    )
    scheduler = ImmediateScheduler()
    compliance = ZeroTagCompliancePolicy()
    service = AiGatewayService(
        prompts=MemoryPromptRepository(
            template() if include_template else None
        ),
        calls=calls,
        provider=provider,
        fallback=RuleBasedFallbackGenerator(compliance),
        scheduler=scheduler,
        compliance=compliance,
        renderer=PromptRenderer(),
        max_compliance_retries=max_retries,
        input_cost_usd_per_million=Decimal("1"),
        output_cost_usd_per_million=Decimal("2"),
    )
    return service, calls, scheduler


async def test_safe_response_is_returned_and_fully_audited() -> None:
    provider = SequenceProvider(
        [provider_response("Plants make food using light.", thought_tokens=2)]
    )
    service, calls, scheduler = service_with(provider)

    result = await service.generate(request())

    assert result.text == "Plants make food using light."
    assert result.fallback_used is False
    assert scheduler.priorities == [AiPriority.ADAPTATION]
    audit = calls.audits[0]
    assert audit.status is AiCallStatus.SUCCEEDED
    assert audit.context.student_id is not None
    assert audit.estimated_cost_usd == Decimal("0.000024")


async def test_zero_tag_violation_is_regenerated_and_usage_is_aggregated() -> None:
    provider = SequenceProvider(
        [
            provider_response("This diagnosis changes the lesson."),
            provider_response(
                "Use one instruction at a time.",
                input_tokens=20,
                output_tokens=7,
            ),
        ]
    )
    service, calls, _ = service_with(provider)

    result = await service.generate(request())

    assert result.text == "Use one instruction at a time."
    assert result.compliance_retries == 1
    assert "Zero-Tag policy" in provider.requests[1].user_content
    audit = calls.audits[0]
    assert audit.input_tokens == 30
    assert audit.output_tokens == 12
    assert audit.compliance_retries == 1


async def test_provider_outage_returns_source_preserving_fallback() -> None:
    provider = SequenceProvider([ProviderUnavailableError()])
    service, calls, _ = service_with(provider)

    result = await service.generate(request())

    assert result.text == "Plants use light to make food."
    assert result.provider is AiProviderName.RULE_BASED
    assert result.fallback_used is True
    audit = calls.audits[0]
    assert audit.status is AiCallStatus.FALLBACK
    assert audit.error_code == "provider_unavailable"


async def test_repeated_noncompliant_responses_fall_back_without_labels() -> None:
    provider = SequenceProvider(
        [
            provider_response("A diagnosis."),
            provider_response("Another diagnosis."),
        ]
    )
    service, calls, _ = service_with(provider, max_retries=1)

    result = await service.generate(request())

    assert result.fallback_used is True
    assert "diagnosis" not in result.text.casefold()
    assert calls.audits[0].error_code == "zero_tag_rejected"


async def test_missing_template_is_rejected_before_provider_call() -> None:
    provider = SequenceProvider([])
    service, _, _ = service_with(provider, include_template=False)

    with pytest.raises(PromptTemplateNotFoundError):
        await service.generate(request())

    assert provider.requests == []


async def test_missing_required_variable_is_rejected() -> None:
    provider = SequenceProvider([])
    service, _, _ = service_with(provider)
    invalid = request()
    invalid = AiGenerationRequest(
        requester_user_id=invalid.requester_user_id,
        service=invalid.service,
        prompt_name=invalid.prompt_name,
        variables={"source_text": "Source"},
    )

    with pytest.raises(PromptVariablesError):
        await service.generate(invalid)
