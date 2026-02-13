from fastapi import APIRouter
from app.api.v1.auth.endpoints.signup import router as signup_router
from app.api.v1.auth.endpoints.login import router as login_router
from app.api.v1.auth.endpoints.forgot_password import router as forgot_password_router
from app.api.v1.auth.endpoints.refresh_token import router as refresh_token_router

auth_router = APIRouter()
auth_router.include_router(signup_router, tags=["Auth"])
auth_router.include_router(login_router, tags=["Auth"])
auth_router.include_router(forgot_password_router, tags=["Auth"])
auth_router.include_router(refresh_token_router, tags=["Auth"])