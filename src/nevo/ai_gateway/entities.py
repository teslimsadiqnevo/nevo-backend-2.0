from dataclasses import dataclass, field
from decimal import Decimal
from uuid import UUID

from nevo.domain.ai_gateway.vocabulary import (
    AiCallStatus,
    AiPriority,
    AiProviderName,
    AiService,
)


@dataclass(frozen=True, slots=True)
class AiRequestContext:
    requester_user_id: UUID
    school_id: UUID | None
    student_id: UUID | None


@dataclass(frozen=True, slots=True)
class AiGenerationRequest:
    requester_user_id: UUID
    service: AiService
    prompt_name: str
    variables: dict[str, str]
    student_id: UUID | None = None
    max_output_tokens: int = 1_024


@dataclass(frozen=True, slots=True)
class PromptTemplate:
    id: UUID
    service: AiService
    name: str
    version: int
    system_template: str
    user_template: str
    required_variables: frozenset[str]


@dataclass(frozen=True, slots=True)
class RenderedPrompt:
    template: PromptTemplate
    system_instruction: str
    user_content: str


@dataclass(frozen=True, slots=True)
class ProviderRequest:
    system_instruction: str
    user_content: str
    max_output_tokens: int


@dataclass(frozen=True, slots=True)
class ProviderResponse:
    text: str
    provider: AiProviderName
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    thought_tokens: int = 0


@dataclass(frozen=True, slots=True)
class AiCallAudit:
    context: AiRequestContext
    template_id: UUID
    service: AiService
    priority: AiPriority
    provider: AiProviderName
    model: str
    status: AiCallStatus
    input_tokens: int
    output_tokens: int
    thought_tokens: int
    latency_ms: int
    estimated_cost_usd: Decimal
    compliance_retries: int
    fallback_used: bool
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class AiGenerationResult:
    text: str
    provider: AiProviderName
    model: str
    prompt_name: str
    prompt_version: int
    fallback_used: bool
    compliance_retries: int
    call_id: UUID


@dataclass(frozen=True, slots=True)
class ComplianceResult:
    allowed: bool
    violations: frozenset[str] = field(default_factory=frozenset)
