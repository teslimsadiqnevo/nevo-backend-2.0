from collections import deque
from uuid import UUID, uuid4

from nevo.ai_gateway.entities import (
    AiCallAudit,
    AiGenerationRequest,
    AiRequestContext,
    PromptTemplate,
    ProviderRequest,
    ProviderResponse,
)
from nevo.ai_gateway.ports import ProviderOperation
from nevo.domain.ai_gateway.vocabulary import AiPriority, AiService


class MemoryPromptRepository:
    def __init__(self, template: PromptTemplate | None) -> None:
        self.template = template

    async def active(
        self,
        *,
        name: str,
        service: AiService,
    ) -> PromptTemplate | None:
        if (
            self.template is None
            or self.template.name != name
            or self.template.service is not service
        ):
            return None
        return self.template


class MemoryCallRepository:
    def __init__(self, context: AiRequestContext) -> None:
        self.context = context
        self.audits: list[AiCallAudit] = []
        self.call_id = uuid4()

    async def resolve_context(
        self,
        *,
        requester_user_id: UUID,
        student_id: UUID | None,
    ) -> AiRequestContext:
        return AiRequestContext(
            requester_user_id=requester_user_id,
            school_id=self.context.school_id,
            student_id=student_id,
        )

    async def record(self, audit: AiCallAudit) -> UUID:
        self.audits.append(audit)
        return self.call_id


class SequenceProvider:
    def __init__(
        self,
        responses: list[ProviderResponse | Exception],
    ) -> None:
        self.responses = deque(responses)
        self.requests: list[ProviderRequest] = []
        self.closed = False

    async def generate(self, request: ProviderRequest) -> ProviderResponse:
        self.requests.append(request)
        response = self.responses.popleft()
        if isinstance(response, Exception):
            raise response
        return response

    async def close(self) -> None:
        self.closed = True


class ImmediateScheduler:
    def __init__(self) -> None:
        self.priorities: list[AiPriority] = []
        self.closed = False

    async def execute(
        self,
        priority: AiPriority,
        operation: ProviderOperation,
    ) -> ProviderResponse:
        self.priorities.append(priority)
        return await operation()

    async def close(self) -> None:
        self.closed = True


class RecordingFallback:
    def __init__(self, response: ProviderResponse) -> None:
        self.response = response
        self.requests: list[AiGenerationRequest] = []

    def generate(
        self,
        request: AiGenerationRequest,
        *,
        user_content: str,
    ) -> ProviderResponse:
        self.requests.append(request)
        return self.response
