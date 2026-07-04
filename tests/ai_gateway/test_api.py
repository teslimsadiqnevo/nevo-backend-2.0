from decimal import Decimal
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from nevo.ai_gateway.compliance import ZeroTagCompliancePolicy
from nevo.ai_gateway.entities import (
    AiRequestContext,
    PromptTemplate,
    ProviderResponse,
)
from nevo.ai_gateway.fallback import RuleBasedFallbackGenerator
from nevo.ai_gateway.prompts import PromptRenderer
from nevo.ai_gateway.service import AiGatewayService
from nevo.api.ai_gateway import router
from nevo.api.auth import authenticated_principal
from nevo.auth.entities import AuthPrincipal
from nevo.domain.ai_gateway.vocabulary import AiProviderName, AiService

from .fakes import (
    ImmediateScheduler,
    MemoryCallRepository,
    MemoryPromptRepository,
    SequenceProvider,
)


def test_authenticated_generation_returns_version_and_call_id() -> None:
    user_id = uuid4()
    context = AiRequestContext(
        requester_user_id=user_id,
        school_id=uuid4(),
        student_id=None,
    )
    calls = MemoryCallRepository(context)
    compliance = ZeroTagCompliancePolicy()
    gateway = AiGatewayService(
        prompts=MemoryPromptRepository(
            PromptTemplate(
                id=uuid4(),
                service=AiService.NARRATIVE,
                name="narrative.default",
                version=1,
                system_template="Use evidence only.",
                user_template="{evidence}",
                required_variables=frozenset({"evidence"}),
            )
        ),
        calls=calls,
        provider=SequenceProvider(
            [
                ProviderResponse(
                    text="The learner completed three activities.",
                    provider=AiProviderName.GEMINI,
                    model="test",
                )
            ]
        ),
        fallback=RuleBasedFallbackGenerator(compliance),
        scheduler=ImmediateScheduler(),
        compliance=compliance,
        renderer=PromptRenderer(),
        max_compliance_retries=1,
        input_cost_usd_per_million=Decimal("0"),
        output_cost_usd_per_million=Decimal("0"),
    )
    principal = AuthPrincipal(
        user_id=user_id,
        role="teacher",
        session_id=uuid4(),
    )
    app = FastAPI()
    app.state.ai_gateway = gateway
    app.dependency_overrides[authenticated_principal] = lambda: principal
    app.include_router(router)

    response = TestClient(app).post(
        "/api/v1/ai/generate",
        json={
            "service": "narrative",
            "prompt_name": "narrative.default",
            "variables": {"evidence": "Three activities completed."},
        },
    )

    assert response.status_code == 200
    assert response.json()["prompt_version"] == 1
    assert response.json()["call_id"] == str(calls.call_id)
    assert response.json()["fallback_used"] is False
