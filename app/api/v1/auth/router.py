from fastapi import APIRouter
from app.api.v1.auth.endpoints.signup import router as signup_router

auth_router = APIRouter()
auth_router.include_router(signup_router, tags=["Auth"])