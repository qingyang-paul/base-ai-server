from fastapi import APIRouter, Depends, status, Request
from fastapi_limiter.depends import RateLimiter
from pydantic import BaseModel, EmailStr, Field

from loguru import logger
from app.auth_service.auth_service import AuthService
from app.dependencies import get_auth_service
from app.auth_service.core.dependencies import get_client_info, ClientInfo

router = APIRouter()

class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)

@router.post("/login", status_code=status.HTTP_200_OK, dependencies=[Depends(RateLimiter(times=5, seconds=60))])
async def login(
    login_data: LoginRequest,
    client_info: ClientInfo = Depends(get_client_info),
    service: AuthService = Depends(get_auth_service)
):
    logger.info(f"Login attempt for {login_data.email} from {client_info.ip_address}")
    tokens = await service.handle_login(
        email=login_data.email, 
        password=login_data.password,
        ip_address=client_info.ip_address,
        user_agent=client_info.device_name
    )
    logger.info(f"Login successful for {login_data.email} from {client_info.ip_address}")
    return tokens
