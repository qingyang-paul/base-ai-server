from fastapi import APIRouter, Depends, status, Body
from pydantic import BaseModel, Field

from app.dependencies import get_current_user_id, get_auth_service
from app.auth_service.auth_service import AuthService

router = APIRouter()

class ChangePasswordRequest(BaseModel):
    old_password: str = Field(..., min_length=8, description="Current password")
    new_password: str = Field(..., min_length=8, description="New password")

@router.post("/change-password", status_code=status.HTTP_200_OK)
async def change_password(
    request: ChangePasswordRequest,
    user_id: str = Depends(get_current_user_id),
    auth_service: AuthService = Depends(get_auth_service),
):
    """
    Change the authenticated user's password.
    
    This will invalidate all existing sessions (Refresh Tokens) for security.
    """
    await auth_service.handle_change_password(
        user_id=user_id,
        old_password=request.old_password,
        new_password=request.new_password
    )
    return {"msg": "Password changed successfully"}
