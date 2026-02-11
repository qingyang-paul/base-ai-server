import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import String, Boolean, Integer, ForeignKey, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.model import Base

class UserModel(Base):
    __tablename__ = "users_auth_info"

    # --- Basic Info ---
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    email: Mapped[str] = mapped_column(String, unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String)
    
    # --- Security Core ---
    refresh_token_version: Mapped[int] = mapped_column(Integer, default=1)
    totp_secret: Mapped[Optional[str]] = mapped_column(String, nullable=True) # Encrypted
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    
    # --- Status & Profile ---
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True) # Ban switch
    nick_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    avatar_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    role: Mapped[str] = mapped_column(String, default="user")

    # --- Security Enhancements ---
    password_changed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    
    # --- Audit ---
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # --- Relationships ---
    # refresh_tokens = relationship("RefreshTokenModel", back_populates="user")


class RefreshTokenModel(Base):
    __tablename__ = "refresh_tokens"

    # Use jti (JWT ID) as primary key, as it is unique in Token
    jti: Mapped[str] = mapped_column(String, primary_key=True)
    
    user_id: Mapped[str] = mapped_column(ForeignKey("users_auth_info.id"), index=True)
    
    # Core Fields: Token Rotation
    family_id: Mapped[str] = mapped_column(String, index=True) # Marks a chain of related Tokens
    parent_jti: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # Who is the previous Token
    
    token_version: Mapped[int] = mapped_column(Integer)
    
    # Status Management
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    replaced_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True) # Keep record for audit even if replaced
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    
    # Audit
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ip_address: Mapped[str] = mapped_column(String)
    device_name: Mapped[str] = mapped_column(String)

    # --- Relationships ---
    # user = relationship("UserModel", back_populates="refresh_tokens")
