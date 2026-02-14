from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from typing import Optional
from loguru import logger

from app.auth_service.auth_service import AuthService
from app.dependencies import get_auth_service

router = APIRouter()

class RefreshTokenRequest(BaseModel):
    refresh_token: str

class AccessTokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"

from fastapi_limiter.depends import RateLimiter
from app.auth_service.core.dependencies import get_client_info, ClientInfo

@router.post("/refresh", response_model=AccessTokenPair, dependencies=[Depends(RateLimiter(times=5, seconds=60))])
async def refresh_token(
    request: RefreshTokenRequest,
    client_info: ClientInfo = Depends(get_client_info),
    auth_service: AuthService = Depends(get_auth_service)
):
    """
    Refresh Access Token and rotate Refresh Token.
    """
    logger.info(f"Refresh token request received from {client_info.ip_address}")
    return await auth_service.handle_refresh_token(
        refresh_token=request.refresh_token,
        ip_address=client_info.ip_address,
        device_name=client_info.device_name
    )
