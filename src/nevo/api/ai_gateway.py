from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator

from nevo.ai_gateway.entities import (
    AiGenerationRequest,
    AiGenerationResult,
)
from nevo.ai_gateway.errors import (
    AiGatewayError,
    InvalidAiContextError,
    PromptTemplateNotFoundError,
)
from nevo.ai_gateway.service import AiGatewayService
from nevo.api.auth import PrincipalDependency
from nevo.domain.ai_gateway.vocabulary import AiProviderName, AiService

router = APIRouter(prefix="/api/v1/ai", tags=["ai-gateway"])


class GenerateRequest(BaseModel):
    service: AiService
    prompt_name: str = Field(min_length=2, max_length=120)
    variables: dict[str, str] = Field(min_length=1)
    student_id: UUID | None = None
    max_output_tokens: int = Field(default=1_024, ge=64, le=8_192)

    @field_validator("variables")
    @classmethod
    def bound_prompt_input(cls, value: dict[str, str]) -> dict[str, str]:
        if len(value) > 24:
            raise ValueError("At most 24 prompt variables are allowed.")
        for key, item in value.items():
            if not key or len(key) > 120 or len(item) > 100_000:
                raise ValueError("Prompt variables exceed the allowed size.")
        return value


class GenerateResponse(BaseModel):
    text: str
    provider: AiProviderName
    model: str
    prompt_name: str
    prompt_version: int
    fallback_used: bool
    compliance_retries: int
    call_id: UUID

    @classmethod
    def from_result(cls, result: AiGenerationResult) -> "GenerateResponse":
        return cls(
            text=result.text,
            provider=result.provider,
            model=result.model,
            prompt_name=result.prompt_name,
            prompt_version=result.prompt_version,
            fallback_used=result.fallback_used,
            compliance_retries=result.compliance_retries,
            call_id=result.call_id,
        )


def get_ai_gateway(request: Request) -> AiGatewayService:
    service = getattr(request.app.state, "ai_gateway", None)
    if not isinstance(service, AiGatewayService):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "service_unavailable",
                "message": "AI generation is temporarily unavailable.",
            },
        )
    return service


AiGatewayDependency = Annotated[
    AiGatewayService,
    Depends(get_ai_gateway),
]


@router.post("/generate", response_model=GenerateResponse)
async def generate(
    payload: GenerateRequest,
    principal: PrincipalDependency,
    gateway: AiGatewayDependency,
) -> GenerateResponse:
    try:
        result = await gateway.generate(
            AiGenerationRequest(
                requester_user_id=principal.user_id,
                service=payload.service,
                prompt_name=payload.prompt_name,
                variables=payload.variables,
                student_id=payload.student_id,
                max_output_tokens=payload.max_output_tokens,
            )
        )
    except AiGatewayError as error:
        raise public_ai_error(error) from error
    return GenerateResponse.from_result(result)


def public_ai_error(error: AiGatewayError) -> HTTPException:
    status_code = status.HTTP_400_BAD_REQUEST
    if isinstance(error, PromptTemplateNotFoundError):
        status_code = status.HTTP_404_NOT_FOUND
    elif isinstance(error, InvalidAiContextError):
        status_code = status.HTTP_403_FORBIDDEN
    return HTTPException(
        status_code=status_code,
        detail={
            "code": error.code,
            "message": error.public_message,
        },
    )
