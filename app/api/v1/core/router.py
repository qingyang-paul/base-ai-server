from fastapi import APIRouter

from app.api.v1.core.endpoints.health import router as health_router

core_router = APIRouter()
core_router.include_router(health_router, tags=["Core"])
