from pydantic import BaseModel, Field
from typing import Literal, Optional
import time
from datetime import datetime

# 1. Base Payload containing common fields
class BaseTokenPayload(BaseModel):
    sub: str          # User ID
    exp: int          # Expiration time
    iat: int = Field(default_factory=lambda: int(time.time())) # Issued At
    iss: str = "auth_service"
    jti: str          # Unique Identifier for the token
    
    # Business fields
    token_version: int # For invalidating all tokens for a user
    role: str

# 2. Access Token
class AccessTokenPayload(BaseTokenPayload):
    # Enforce type to prevent misuse
    type: Literal["access"] = "access"

# 3. Refresh Token
class RefreshTokenPayload(BaseTokenPayload):
    type: Literal["refresh"] = "refresh"
    
    # Required for Token Rotation
    family_id: str 
    parent_jti: Optional[str] = None

# 4. Magic Link / OTP Token
class MagicLinkPayload(BaseTokenPayload):
    # Allow multiple types or subdivide into different classes
    type: Literal["magic_link", "password_reset", "verify_email"]
    
    email: str  # Email is required as user might not be logged in/registered

# --- User Schemas ---

from uuid import UUID

class UserUpdateSchema(BaseModel):
    is_verified: Optional[bool] = None
    hashed_password: Optional[str] = None
    nick_name: Optional[str] = None
    avatar_url: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None
    refresh_token_version: Optional[int] = None
    last_login_at: Optional[datetime] = None
    password_changed_at: Optional[datetime] = None

class UserInternalSchema(BaseModel):
    id: UUID
    email: str
    hashed_password: str
    nick_name: Optional[str] = None
    avatar_url: Optional[str] = None
    is_verified: bool
    is_active: bool
    role: str
    refresh_token_version: int
    created_at: datetime
    updated_at: datetime
    last_login_at: Optional[datetime] = None
