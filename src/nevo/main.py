from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from nevo.api.auth import router as auth_router
from nevo.auth.config import AuthSettings
from nevo.auth.wiring import build_auth_service
from nevo.core.config import get_settings
from nevo.db.session import create_engine, create_session_factory


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    engine = create_engine(get_settings().database_url)
    app.state.auth_service = build_auth_service(
        create_session_factory(engine),
        AuthSettings(),  # type: ignore[call-arg]  # Values come from environment.
    )
    yield
    await engine.dispose()


app = FastAPI(title="Nevo Backend", version="2.0.0", lifespan=lifespan)
app.include_router(auth_router)


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
