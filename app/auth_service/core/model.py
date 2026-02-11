from pydantic import BaseModel, Field
from typing import Literal
import time

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

# 4. Magic Link / OTP Token
class MagicLinkPayload(BaseTokenPayload):
    # Allow multiple types or subdivide into different classes
    type: Literal["magic_link", "password_reset", "verify_email"]
    
    email: str  # Email is required as user might not be logged in/registered
