"""API route aggregation."""

from fastapi import APIRouter

from app.api.approvals import router as approvals_router
from app.api.chat import router as chat_router
from app.api.checkout import router as checkout_router
from app.api.health import router as health_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(chat_router)
api_router.include_router(approvals_router)
api_router.include_router(checkout_router)
