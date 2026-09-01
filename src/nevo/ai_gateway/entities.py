from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
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
    sensitive_terms: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AiGenerationRequest:
    requester_user_id: UUID
    service: AiService
    prompt_name: str
    variables: dict[str, str]
    student_id: UUID | None = None
    max_output_tokens: int = 1_024
    model: str | None = None
    cache_prompt: bool = True


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
class ToolCall:
    """A tool the model asked to run, and the id its result must carry back."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ToolResult:
    id: str
    content: str
    is_error: bool = False


@dataclass(frozen=True, slots=True)
class ProviderRequest:
    system_instruction: str
    user_content: str
    max_output_tokens: int
    model: str | None = None
    cache_prompt: bool = True
    #: Tool schemas the model may call. Empty means a plain text completion,
    #: which is what every existing caller gets.
    tools: tuple[dict[str, Any], ...] = ()
    #: Prior assistant/tool turns, replayed so the model can continue a tool
    #: conversation. The provider owns the wire format; callers pass these
    #: back opaquely.
    history: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class ProviderResponse:
    text: str
    provider: AiProviderName
    model: str
    #: Populated when the model stopped to ask for tools. The caller runs them
    #: and calls again with the results appended to history.
    tool_calls: tuple[ToolCall, ...] = ()
    #: The assistant turn exactly as returned, to be replayed as history.
    raw_content: tuple[dict[str, Any], ...] = ()
    input_tokens: int = 0
    output_tokens: int = 0
    thought_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


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
