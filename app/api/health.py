"""Health check — GET /health."""

from pydantic import BaseModel
from fastapi import APIRouter

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str


@router.get("/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    return HealthResponse(status="ok")
