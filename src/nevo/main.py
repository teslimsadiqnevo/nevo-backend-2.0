from fastapi import FastAPI

app = FastAPI(title="Nevo Backend", version="2.0.0")


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
