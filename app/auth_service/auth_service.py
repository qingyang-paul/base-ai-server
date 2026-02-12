import uuid
import secrets
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional

from loguru import logger

from app.auth_service.auth_repo import AuthRepo
from app.auth_service.core.exceptions import (
    DuplicateEmailError,
    OTPRateLimitError,
    InvalidOTPError,
    UserNotFoundError,
    InvalidPasswordError,
    AccountLockedError,
    EmailNotVerifiedError,
)
from app.auth_service.core.security import get_password_hash, create_token, verify_password
from app.auth_service.tasks.send_email import send_email_task
from app.auth_service.core.config import settings as auth_settings

from app.auth_service.core.schema import UserUpdateSchema

class AuthService:
    def __init__(self, repo: AuthRepo):
        self.repo = repo

    async def handle_signup(self, email: str, password: str, nickname: Optional[str] = None):
        logger.info(f"Signup attempt for {email}")
        
        async with self.repo.connection.transaction():
            # 1. Check Rate Limit (Cool down)
            ttl = await self.repo.get_otp_ttl(email, purpose="signup")
            if ttl > 240:
                logger.warning(f"Rate limit triggered for {email}")
                raise OTPRateLimitError()

            # 2. Check User Existence
            user = await self.repo.get_user_by_email(email)
            if user:
                if user.is_verified:
                    logger.warning(f"Duplicate signup for verified email {email}")
                    raise DuplicateEmailError()
                # If not verified, we overwrite (update) the user.
            
            # 3. Hash Password
            hashed_pw = get_password_hash(password)
            
            # 4. Create/Update User
            if not user:
                user_data = {
                    "email": email,
                    "hashed_password": hashed_pw,
                    "nick_name": nickname,
                    "is_verified": False,
                    "is_active": True,
                }
                await self.repo.create_user(user_data)
                logger.info(f"Created new user record for {email}")
            else:
                updates = UserUpdateSchema(
                    hashed_password=hashed_pw,
                    nick_name=nickname
                )
                await self.repo.update_user(user.id, updates)
                logger.info(f"Updated existing unverified user {email}")
            
            # 5. Generate OTP (6-digit)
            code = f"{secrets.randbelow(1000000):06d}"
            
            # 6. Save OTP
            await self.repo.save_otp(email, code, purpose="signup")
            
            # 7. Send Email (Async)
            await send_email_task.kiq(email, "Verify your email", f"Your verification code is: {code}")
            logger.info(f"Signup flow completed for {email}, email task scheduled")

    async def handle_verify_email(self, email: str, code: str) -> Dict[str, str]:
        logger.info(f"Verify email attempt for {email}")
        
        async with self.repo.connection.transaction():
            # 1. Verify Code
            saved_code = await self.repo.get_otp(email, purpose="signup")
            if not saved_code or saved_code != code:
                logger.warning(f"Invalid OTP for {email}")
                raise InvalidOTPError()
                
            # 2. Get User
            user = await self.repo.get_user_by_email(email)
            if not user:
                 logger.error(f"User not found for verify {email}")
                 raise UserNotFoundError()
            
            # 3. Update User Verified
            updates = UserUpdateSchema(is_verified=True)
            await self.repo.update_user(user.id, updates)
            # Update local user object for token generation if needed
            # user.is_verified = True # (user is pydantic model now, not ORM object attached to session)
            # Actually user is UserInternalSchema (Pydantic), so `user.is_verified = True` works but doesn't persist.
            # But we use `user` downstream for token generation.
            # For correctness, we should update the local object too if used for claims.
            logger.info(f"User {email} verified successfully")
            
            # 4. Generate Tokens
            # Access Token
            access_payload = {
                "sub": str(user.id),
                "role": user.role,
                "token_version": user.refresh_token_version, # Correct field name
                "type": "access",
                "jti": str(uuid.uuid4()),
            }
            access_token = create_token(access_payload, expires_delta=timedelta(minutes=auth_settings.ACCESS_TOKEN_EXPIRE_MINUTES))
            
            # Refresh Token
            family_id = str(uuid.uuid4())
            refresh_payload = {
                "sub": str(user.id),
                "role": user.role,
                "token_version": user.refresh_token_version,
                "type": "refresh",
                "family_id": family_id,
                "jti": str(uuid.uuid4()),
            }
            refresh_token = create_token(refresh_payload, expires_delta=timedelta(days=auth_settings.REFRESH_TOKEN_EXPIRE_DAYS))

            # 5. Delete OTP
            await self.repo.delete_otp(email, purpose="signup")
            
            return {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "token_type": "bearer",
            }

    async def handle_login(self, email: str, password: str, ip_address: str = "0.0.0.0", user_agent: str = "unknown"):
        # 1. Authenticate
        user = await self._authenticate_user(email, password)
        
        # 2. Generate Tokens
        curr_time = datetime.now(timezone.utc)
        tokens = self._generate_tokens(user, curr_time)
        
        # 3. Record Login Activity (Async DB write)
        await self._record_login_activity(
            user=user, 
            refresh_token_payload=tokens["refresh_payload"], 
            ip_address=ip_address, 
            user_agent=user_agent,
            curr_time=curr_time
        )
        
        return {
            "access_token": tokens["access_token"],
            "refresh_token": tokens["refresh_token"],
            "token_type": "bearer",
        }

    async def _authenticate_user(self, email: str, password: str):
        # Retrieve user
        user = await self.repo.get_user_by_email(email)
        if not user:
            # To prevent user enumeration, we might want to fake verification time, 
            # but for now we follow the spec to raise generic or specific error.
            # Security Note: Ideally return "Invalid credentials" for both UserNotFound and InvalidPassword
            raise UserNotFoundError()
            
        # Verify Password
        if not verify_password(password, user.hashed_password):
            raise InvalidPasswordError()
            
        # Check Status
        if not user.is_verified:
            raise EmailNotVerifiedError()
            
        if not user.is_active:
            raise AccountLockedError()
            
        return user

    def _generate_tokens(self, user, curr_time: datetime):
        # Access Token
        access_payload = {
            "sub": str(user.id),
            "role": user.role,
            "token_version": user.refresh_token_version,
            "type": "access",
            "jti": str(uuid.uuid4()),
        }
        access_token = create_token(access_payload, expires_delta=timedelta(minutes=auth_settings.ACCESS_TOKEN_EXPIRE_MINUTES))
        
        # Refresh Token
        family_id = str(uuid.uuid4()) # New login = New Family
        refresh_payload = {
            "sub": str(user.id),
            "role": user.role,
            "token_version": user.refresh_token_version,
            "type": "refresh",
            "family_id": family_id,
            "jti": str(uuid.uuid4()),
        }
        refresh_token = create_token(refresh_payload, expires_delta=timedelta(days=auth_settings.REFRESH_TOKEN_EXPIRE_DAYS))
        
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "access_payload": access_payload,
            "refresh_payload": refresh_payload
        }

    async def _record_login_activity(self, user, refresh_token_payload, ip_address: str, user_agent: str, curr_time: datetime):
        async with self.repo.connection.transaction():
            # Update Last Login
            updates = UserUpdateSchema(last_login_at=curr_time)
            await self.repo.update_user(user.id, updates)
            
            # Save Refresh Token
            expires_at = curr_time + timedelta(days=auth_settings.REFRESH_TOKEN_EXPIRE_DAYS)
            token_data = {
                "jti": refresh_token_payload["jti"],
                "user_id": str(user.id),
                "family_id": refresh_token_payload["family_id"],
                "token_version": refresh_token_payload["token_version"],
                "expires_at": expires_at,
                "created_at": curr_time,
                "ip_address": ip_address,
                "device_name": user_agent,
                # parent_jti is None for new login
            }
            await self.repo.create_refresh_token(token_data)