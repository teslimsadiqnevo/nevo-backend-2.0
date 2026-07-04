from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nevo.ai_gateway.entities import (
    AiCallAudit,
    AiRequestContext,
    PromptTemplate,
)
from nevo.ai_gateway.errors import InvalidAiContextError
from nevo.db.models.account import User
from nevo.db.models.ai_gateway import AiGatewayCall, AiPromptTemplate
from nevo.domain.accounts.vocabulary import UserRole, UserStatus
from nevo.domain.ai_gateway.vocabulary import AiService


class SqlAlchemyPromptTemplateRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def active(
        self,
        *,
        name: str,
        service: AiService,
    ) -> PromptTemplate | None:
        async with self._sessions() as session:
            record = await session.scalar(
                select(AiPromptTemplate).where(
                    AiPromptTemplate.name == name,
                    AiPromptTemplate.service == service,
                    AiPromptTemplate.active.is_(True),
                )
            )
        if record is None:
            return None
        return PromptTemplate(
            id=record.id,
            service=record.service,
            name=record.name,
            version=record.version,
            system_template=record.system_template,
            user_template=record.user_template,
            required_variables=frozenset(record.required_variables),
        )


class SqlAlchemyAiCallRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def resolve_context(
        self,
        *,
        requester_user_id: UUID,
        student_id: UUID | None,
    ) -> AiRequestContext:
        async with self._sessions() as session:
            requester = await session.scalar(
                select(User).where(
                    User.id == requester_user_id,
                    User.status != UserStatus.DEACTIVATED,
                )
            )
            if requester is None:
                raise InvalidAiContextError
            resolved_student_id = student_id
            if student_id is not None:
                student = await session.scalar(
                    select(User.id).where(
                        User.id == student_id,
                        User.school_id == requester.school_id,
                        User.role == UserRole.STUDENT,
                        User.status != UserStatus.DEACTIVATED,
                    )
                )
                if student is None:
                    raise InvalidAiContextError
        return AiRequestContext(
            requester_user_id=requester.id,
            school_id=requester.school_id,
            student_id=resolved_student_id,
        )

    async def record(self, audit: AiCallAudit) -> UUID:
        call_id = uuid4()
        async with self._sessions.begin() as session:
            session.add(
                AiGatewayCall(
                    id=call_id,
                    school_id=audit.context.school_id,
                    requester_user_id=audit.context.requester_user_id,
                    student_id=audit.context.student_id,
                    prompt_template_id=audit.template_id,
                    service=audit.service,
                    priority=int(audit.priority),
                    provider=audit.provider,
                    model=audit.model,
                    status=audit.status,
                    input_tokens=audit.input_tokens,
                    output_tokens=audit.output_tokens,
                    thought_tokens=audit.thought_tokens,
                    latency_ms=audit.latency_ms,
                    estimated_cost_usd=audit.estimated_cost_usd,
                    compliance_retries=audit.compliance_retries,
                    fallback_used=audit.fallback_used,
                    error_code=audit.error_code,
                )
            )
        return call_id
