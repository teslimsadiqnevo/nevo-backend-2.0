from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from nevo.api.auth import router as auth_router
from nevo.api.permissions import router as permission_router
from nevo.auth.config import AuthSettings
from nevo.auth.wiring import build_auth_service, build_credential_hasher
from nevo.core.config import get_settings
from nevo.db.session import create_engine, create_session_factory
from nevo.permissions.wiring import build_permission_service


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
    yield
    await engine.dispose()


app = FastAPI(title="Nevo Backend", version="2.0.0", lifespan=lifespan)
app.include_router(auth_router)
app.include_router(permission_router)


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
