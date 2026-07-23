from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from nevo.ai_gateway.config import AiGatewaySettings
from nevo.ai_gateway.wiring import build_ai_gateway
from nevo.api.ai_gateway import router as ai_gateway_router
from nevo.api.ask_nevo import router as ask_nevo_router
from nevo.api.auth import router as auth_router
from nevo.api.consent import router as consent_router
from nevo.api.docs import (
    API_DESCRIPTION,
    OPENAPI_TAGS,
    SWAGGER_UI_PARAMETERS,
    stable_operation_id,
)
from nevo.api.intelligence import router as intelligence_router
from nevo.api.permissions import router as permission_router
from nevo.api.signals import router as signals_router
from nevo.api.sso import router as sso_router
from nevo.api.teacher_assignments import router as teacher_assignment_router
from nevo.ask_nevo.wiring import build_ask_nevo_service
from nevo.attention_flags.wiring import build_attention_flag_detection_service
from nevo.auth.config import AuthSettings
from nevo.auth.wiring import build_auth_service, build_credential_hasher
from nevo.consent.config import ConsentSettings
from nevo.consent.wiring import build_consent_service
from nevo.core.config import get_settings
from nevo.db.session import create_engine, create_session_factory
from nevo.intelligence.wiring import build_adaptation_engine_service
from nevo.learner_profiles.wiring import (
    build_post_lesson_profile_update_service,
)
from nevo.permissions.wiring import build_permission_service
from nevo.signal_events.wiring import build_signal_ingestion_service
from nevo.sso.config import SsoSettings
from nevo.sso.wiring import build_sso_service
from nevo.teacher_assignments.wiring import build_teacher_assignment_service


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    engine = create_engine(get_settings().database_url)
    sessions = create_session_factory(engine)
    auth_settings = AuthSettings()  # type: ignore[call-arg]
    credential_hasher = build_credential_hasher(auth_settings)
    app.state.auth_service = build_auth_service(
        sessions,
        auth_settings,
        credential_hasher=credential_hasher,
    )
    app.state.permission_service = build_permission_service(
        sessions,
        credential_hasher=credential_hasher,
        session_pepper=auth_settings.auth_session_pepper.get_secret_value(),
    )
    app.state.teacher_assignment_service = build_teacher_assignment_service(
        sessions
    )
    consent_settings = ConsentSettings()
    app.state.consent_service = build_consent_service(
        sessions,
        token_pepper=auth_settings.auth_session_pepper.get_secret_value(),
        public_base_url=str(consent_settings.public_base_url),
    )
    app.state.ai_gateway = build_ai_gateway(
        sessions,
        AiGatewaySettings(),
    )
    app.state.sso_service = build_sso_service(
        sessions,
        auth_settings,
        SsoSettings(),
    )
    app.state.ask_nevo_service = build_ask_nevo_service(
        sessions,
        app.state.ai_gateway,
    )
    app.state.post_lesson_profile_update_service = (
        build_post_lesson_profile_update_service(
            sessions,
            app.state.ai_gateway,
        )
    )
    app.state.attention_flag_detection_service = (
        build_attention_flag_detection_service(
            sessions,
            app.state.ai_gateway,
        )
    )
    app.state.adaptation_engine_service = build_adaptation_engine_service(
        sessions,
        app.state.ai_gateway,
    )
    app.state.signal_ingestion_service = build_signal_ingestion_service(
        sessions,
    )
    try:
        yield
    finally:
        await app.state.ai_gateway.close()
        await engine.dispose()


app = FastAPI(
    title="Nevo Backend API",
    summary="Functional learning platform backend for Nevo.",
    description=API_DESCRIPTION,
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    openapi_tags=OPENAPI_TAGS,
    swagger_ui_parameters=SWAGGER_UI_PARAMETERS,
    generate_unique_id_function=stable_operation_id,
)
app.include_router(ai_gateway_router)
app.include_router(ask_nevo_router)
app.include_router(auth_router)
app.include_router(consent_router)
app.include_router(intelligence_router)
app.include_router(permission_router)
app.include_router(signals_router)
app.include_router(sso_router)
app.include_router(teacher_assignment_router)


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
