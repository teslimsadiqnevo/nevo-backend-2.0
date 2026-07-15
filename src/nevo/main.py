from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from nevo.ai_gateway.config import AiGatewaySettings
from nevo.ai_gateway.wiring import build_ai_gateway
from nevo.api.ai_gateway import router as ai_gateway_router
from nevo.api.auth import router as auth_router
from nevo.api.consent import router as consent_router
from nevo.api.permissions import router as permission_router
from nevo.api.signals import router as signals_router
from nevo.api.teacher_assignments import router as teacher_assignment_router
from nevo.attention_flags.wiring import build_attention_flag_detection_service
from nevo.auth.config import AuthSettings
from nevo.auth.wiring import build_auth_service, build_credential_hasher
from nevo.consent.config import ConsentSettings
from nevo.consent.wiring import build_consent_service
from nevo.core.config import get_settings
from nevo.db.session import create_engine, create_session_factory
from nevo.learner_profiles.wiring import (
    build_post_lesson_profile_update_service,
)
from nevo.permissions.wiring import build_permission_service
from nevo.signal_events.wiring import build_signal_ingestion_service
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
    app.state.signal_ingestion_service = build_signal_ingestion_service(
        sessions,
    )
    try:
        yield
    finally:
        await app.state.ai_gateway.close()
        await engine.dispose()


app = FastAPI(title="Nevo Backend", version="2.0.0", lifespan=lifespan)
app.include_router(ai_gateway_router)
app.include_router(auth_router)
app.include_router(consent_router)
app.include_router(permission_router)
app.include_router(signals_router)
app.include_router(teacher_assignment_router)


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
