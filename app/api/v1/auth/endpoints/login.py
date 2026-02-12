from fastapi import APIRouter, Depends, status, Request
from fastapi_limiter.depends import RateLimiter
from pydantic import BaseModel, EmailStr, Field

from app.auth_service.auth_service import AuthService
from app.dependencies import get_auth_service

router = APIRouter()

class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)

@router.post("/login", status_code=status.HTTP_200_OK, dependencies=[Depends(RateLimiter(times=5, seconds=60))])
async def login(
    request: Request,
    login_data: LoginRequest,
    service: AuthService = Depends(get_auth_service)
):
    val_ip = request.client.host if request.client else "0.0.0.0"
    val_ua = request.headers.get("user-agent", "unknown")
    
    tokens = await service.handle_login(
        email=login_data.email, 
        password=login_data.password,
        ip_address=val_ip,
        user_agent=val_ua
    )
    return tokens
