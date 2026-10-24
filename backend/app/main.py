"""Minimal FastAPI foundation owned by the shared backend team."""

from fastapi import FastAPI

app = FastAPI()


@app.get("/health")
async def health() -> dict[str, str]:
    """Provide a dependency-free readiness check for local development."""

    return {"status": "ok"}
