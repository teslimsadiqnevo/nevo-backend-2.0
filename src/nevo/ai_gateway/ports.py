from collections.abc import Awaitable, Callable
from typing import Protocol
from uuid import UUID

from nevo.ai_gateway.entities import (
    AiCallAudit,
    AiGenerationRequest,
    AiRequestContext,
    PromptTemplate,
    ProviderRequest,
    ProviderResponse,
)
from nevo.domain.ai_gateway.vocabulary import AiPriority, AiService


class PromptTemplateRepository(Protocol):
    async def active(
        self,
        *,
        name: str,
        service: AiService,
    ) -> PromptTemplate | None: ...


class AiCallRepository(Protocol):
    async def resolve_context(
        self,
        *,
        requester_user_id: UUID,
        student_id: UUID | None,
    ) -> AiRequestContext: ...

    async def record(self, audit: AiCallAudit) -> UUID: ...


class TextGenerationProvider(Protocol):
    async def generate(self, request: ProviderRequest) -> ProviderResponse: ...

    async def close(self) -> None: ...


class FallbackGenerator(Protocol):
    def generate(
        self,
        request: AiGenerationRequest,
        *,
        user_content: str,
    ) -> ProviderResponse: ...


ProviderOperation = Callable[[], Awaitable[ProviderResponse]]


class RequestScheduler(Protocol):
    async def execute(
        self,
        priority: AiPriority,
        operation: ProviderOperation,
    ) -> ProviderResponse: ...

    async def close(self) -> None: ...
