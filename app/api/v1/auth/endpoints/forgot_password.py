from fastapi import APIRouter, Depends, status, Request, Body
from fastapi_limiter.depends import RateLimiter
from pydantic import BaseModel, EmailStr, Field

from app.auth_service.auth_service import AuthService
from app.dependencies import get_auth_service

router = APIRouter()

class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class VerifyResetCodeRequest(BaseModel):
    email: EmailStr
    code: str

class ResetPasswordRequest(BaseModel):
    reset_token: str
    new_password: str = Field(min_length=8)

@router.post(
    "/forgot-password", 
    status_code=status.HTTP_200_OK, 
    dependencies=[Depends(RateLimiter(times=3, seconds=60))]
)
async def forgot_password(
    request: ForgotPasswordRequest,
    service: AuthService = Depends(get_auth_service)
):
    await service.handle_forgot_password(request.email)
    # Return vague message to prevent enumeration
    return {"msg": f"If an account exists for {request.email}, you will receive a verification code shortly."}

@router.post(
    "/verify-reset-code", 
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(RateLimiter(times=5, seconds=60))]
)
async def verify_reset_code(
    request: VerifyResetCodeRequest,
    service: AuthService = Depends(get_auth_service)
):
    result = await service.handle_verify_reset_code(request.email, request.code)
    # Returns {"otp_token": ...}
    return result

@router.post(
    "/reset-password",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(RateLimiter(times=3, seconds=60))]
)
async def reset_password(
    request: ResetPasswordRequest,
    service: AuthService = Depends(get_auth_service)
):
    await service.handle_reset_password(request.reset_token, request.new_password)
    return {"msg": "Password reset successfully."}
