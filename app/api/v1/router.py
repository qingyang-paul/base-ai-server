from fastapi import APIRouter

from app.api.v1.auth.router import auth_router
from app.api.v1.core.router import core_router
from app.api.v1.session.router import session_router

api_router = APIRouter()
api_router.include_router(core_router, prefix="/core", tags=["Core"])
api_router.include_router(auth_router, prefix="/auth")
api_router.include_router(session_router, prefix="/session")
