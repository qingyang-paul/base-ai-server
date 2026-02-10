from fastapi import APIRouter

from app.api.v1.core.router import core_router

api_router = APIRouter()
api_router.include_router(core_router, prefix="/core", tags=["Core"])
