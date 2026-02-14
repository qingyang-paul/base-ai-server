from fastapi import APIRouter, Depends, status, Request
from fastapi_limiter.depends import RateLimiter
from pydantic import BaseModel, EmailStr, Field

from loguru import logger
from app.auth_service.auth_service import AuthService
from app.dependencies import get_auth_service

router = APIRouter()

class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    nickname: str | None = None

class VerifyEmailRequest(BaseModel):
    email: EmailStr
    code: str

@router.post("/signup", status_code=status.HTTP_200_OK, dependencies=[Depends(RateLimiter(times=5, seconds=60))])
async def signup(
    request: Request,
    signup_data: SignupRequest,
    service: AuthService = Depends(get_auth_service)
):
    # trace_id is handled by middleware
    logger.info(f"Signup request received for {signup_data.email}")
    await service.handle_signup(signup_data.email, signup_data.password, signup_data.nickname)
    logger.info(f"Signup request processed for {signup_data.email}")
    return {"msg": "success"}

@router.post("/verify-email", status_code=status.HTTP_200_OK, dependencies=[Depends(RateLimiter(times=5, seconds=60))])
async def verify_email(
    request: VerifyEmailRequest,
    service: AuthService = Depends(get_auth_service)
):
    logger.info(f"Verify email request received for {request.email}")
    tokens = await service.handle_verify_email(request.email, request.code)
    logger.info(f"Verify email successful for {request.email}")
    return tokens
