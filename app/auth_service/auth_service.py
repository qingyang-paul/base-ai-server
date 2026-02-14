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
    AccountLockedError,
    EmailNotVerifiedError,
    InvalidResetTokenError,
)
from app.auth_service.core.security import get_password_hash, create_token, verify_password, decode_token
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

            # Save Refresh Token
            curr_time = datetime.now(timezone.utc)
            expires_at = curr_time + timedelta(days=auth_settings.REFRESH_TOKEN_EXPIRE_DAYS)
            token_data = {
                "jti": refresh_payload["jti"],
                "user_id": str(user.id),
                "family_id": refresh_payload["family_id"],
                "token_version": refresh_payload["token_version"],
                "expires_at": expires_at,
                "created_at": curr_time,
                "ip_address": "0.0.0.0",
                "device_name": "unknown"
            }
            await self.repo.create_refresh_token(token_data)

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
            logger.warning(f"Authentication failed: User {email} not found")
            raise UserNotFoundError()
            
        # Verify Password
        if not verify_password(password, user.hashed_password):
            logger.warning(f"Authentication failed: Invalid password for user {email}")
            raise InvalidPasswordError()
            
        # Check Status
        if not user.is_verified:
            logger.warning(f"Authentication failed: Email {email} not verified")
            raise EmailNotVerifiedError()
            
        if not user.is_active:
            logger.warning(f"Authentication failed: Account {email} is locked/inactive")
            raise AccountLockedError()
            
        logger.info(f"User {email} authenticated successfully")
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

    async def handle_refresh_token(self, refresh_token: str, ip_address: str = "0.0.0.0", device_name: str = "unknown") -> Dict[str, str]:
        logger.info(f"Handle refresh token request from IP: {ip_address}")
        # 1. Decode & Basic Validation
        try:
            payload = decode_token(refresh_token)
        except Exception:
            # Log the attempt details for security auditing
            logger.warning(f"Invalid refresh token attempt from IP: {ip_address}, Device: {device_name}")
            raise InvalidResetTokenError() # Using Generic Error for security

        if payload.get("type") != "refresh":
            logger.warning(f"Token type mismatch from IP: {ip_address}")
            raise InvalidResetTokenError()

        jti = payload.get("jti")
        sub = payload.get("sub")
        
        reuse_error = False
        
        async with self.repo.connection.transaction():
            # 2. Check DB Status
            rt_record = await self.repo.get_refresh_token_by_jti(jti)
            if not rt_record:
                # Token not in DB? Either expired/cleaned up or forged.
                logger.warning(f"Refresh token not found in DB: {jti}")
                raise InvalidResetTokenError()
                
            # 3. Check Revocation
            if rt_record.get("revoked_at"):
                # Explicitly revoked
                logger.warning(f"Refresh token revoked: {jti}")
                raise InvalidResetTokenError()

            # 4. Check Replacement (Reuse Detection)
            replaced_at = rt_record.get("replaced_at")
            if replaced_at:
                # Ensure timezone awareness
                if replaced_at.tzinfo is None:
                    replaced_at = replaced_at.replace(tzinfo=timezone.utc)
                
                now = datetime.now(timezone.utc)
                time_since_replacement = (now - replaced_at).total_seconds()
                
                if time_since_replacement > 30: 
                    # > 30s: Reuse Attack -> Revoke Everything
                    logger.warning(f"Refresh Token Reuse Attack detected for user {sub}. JTI: {jti}")
                    await self.repo.revoke_all_tokens_for_user(sub)
                    reuse_error = True
                    # Exit block to commit revocation
                else:
                    # < 30s: Grace Period -> Return existing valid tokens
                    family_id = rt_record.get("family_id")
                    latest_token = await self.repo.get_latest_token_in_family(family_id)
                    
                    if not latest_token:
                         logger.warning(f"Grace period: No tokens found in family {family_id}")
                         raise InvalidResetTokenError()
                         
                    # Reconstruct Access Token (NEW)
                    user = await self.repo.get_user_by_id(sub)
                    if not user:
                        logger.error(f"Grace period: User {sub} not found during token reconstruction")
                        raise UserNotFoundError()
                        
                    access_payload = {
                        "sub": str(user.id),
                        "role": user.role,
                        "token_version": user.refresh_token_version,
                        "type": "access",
                        "jti": str(uuid.uuid4()),
                    }
                    access_token = create_token(access_payload, expires_delta=timedelta(minutes=auth_settings.ACCESS_TOKEN_EXPIRE_MINUTES))
                    
                    # Reconstruct Refresh Token (Using LATEST JTI)
                    refresh_payload = {
                        "sub": str(user.id),
                        "role": user.role,
                        "token_version": user.refresh_token_version,
                        "type": "refresh",
                        "family_id": family_id,
                        "jti": latest_token["jti"],
                    }
                    new_refresh_token = create_token(refresh_payload, expires_delta=timedelta(days=auth_settings.REFRESH_TOKEN_EXPIRE_DAYS))
                    
                    return {
                        "access_token": access_token,
                        "refresh_token": new_refresh_token,
                        "token_type": "bearer",
                    }
            
            # 5. Normal Rotation (Valid, Active Token)
            # Only proceed if NOT replaced and NOT reuse error
            if not replaced_at and not reuse_error:
                user = await self.repo.get_user_by_id(sub)
                if not user:
                    logger.warning(f"User not found: {sub}")
                    raise UserNotFoundError()
    
                # Check User Token Version
                if user.refresh_token_version != payload.get("token_version"):
                    logger.warning(f"Token version mismatch: user={user.refresh_token_version}, token={payload.get('token_version')}")
                    raise InvalidResetTokenError()
    
                # Mark current as replaced
                current_time = datetime.now(timezone.utc)
                await self.repo.update_refresh_token(jti, {"replaced_at": current_time})
                
                # Generate NEW Tokens
                access_payload = {
                    "sub": str(user.id),
                    "role": user.role,
                    "token_version": user.refresh_token_version,
                    "type": "access",
                    "jti": str(uuid.uuid4()),
                }
                access_token = create_token(access_payload, expires_delta=timedelta(minutes=auth_settings.ACCESS_TOKEN_EXPIRE_MINUTES))
                
                family_id = payload.get("family_id")
                new_jti = str(uuid.uuid4())
                refresh_payload = {
                    "sub": str(user.id),
                    "role": user.role,
                    "token_version": user.refresh_token_version,
                    "type": "refresh",
                    "family_id": family_id,
                    "jti": new_jti,
                }
                refresh_token = create_token(refresh_payload, expires_delta=timedelta(days=auth_settings.REFRESH_TOKEN_EXPIRE_DAYS))
                
                # Persist New Refresh Token
                expires_at = current_time + timedelta(days=auth_settings.REFRESH_TOKEN_EXPIRE_DAYS)
                token_data = {
                    "jti": new_jti,
                    "user_id": str(user.id),
                    "family_id": family_id,
                    "token_version": user.refresh_token_version,
                    "expires_at": expires_at,
                    "created_at": current_time,
                    "ip_address": ip_address,
                    "device_name": device_name,
                    "parent_jti": jti,
                }
                await self.repo.create_refresh_token(token_data)
                
                return {
                    "access_token": access_token,
                    "refresh_token": refresh_token,
                    "token_type": "bearer",
                }

        # Raise exception OUTSIDE transaction block
        if reuse_error:
            raise InvalidResetTokenError()
 

    async def handle_forgot_password(self, email: str):
        logger.info(f"Forgot password request for {email}")
        
        # 1. Check User Existence
        user = await self.repo.get_user_by_email(email)
        if not user:
            # Avoid user enumeration: pretend success
            logger.info(f"User {email} not found, simulating success for forgot password")
            return

        # 2. Check Rate Limit
        # We can reuse the same rate limit logic or a separate one
        ttl = await self.repo.get_otp_ttl(email, purpose="reset_password")
        if ttl > 240: # 60s cooldown (TTL starts at 300)
             logger.warning(f"Rate limit triggered for forgot password {email}")
             raise OTPRateLimitError()

        # 3. Generate OTP
        code = f"{secrets.randbelow(1000000):06d}"
        
        # 4. Save OTP
        await self.repo.save_otp(email, code, purpose="reset_password")
        
        # 5. Send Email
        await send_email_task.kiq(email, "Reset your password", f"Your password reset code is: {code}")
        logger.info(f"Forgot password OTP sent to {email}")

    async def handle_verify_reset_code(self, email: str, code: str) -> Dict[str, str]:
        logger.info(f"Verifying reset code for {email}")
        
        # 1. Verify OTP
        saved_code = await self.repo.get_otp(email, purpose="reset_password")
        if not saved_code or saved_code != code:
            logger.warning(f"Invalid reset OTP for {email}")
            raise InvalidOTPError()
            
        # 2. Get User (Should exist if OTP exists, but good to check)
        user = await self.repo.get_user_by_email(email)
        if not user:
             logger.error(f"User not found during reset code verification {email}")
             raise UserNotFoundError()

        # 3. Generate Reset Token (Magic Link Token)
        # Short lived, e.g., 15 minutes
        reset_payload = {
            "sub": str(user.id),
            "email": user.email,
            "type": "password_reset",
            "jti": str(uuid.uuid4()),
        }
        reset_token = create_token(reset_payload, expires_delta=timedelta(minutes=15))
        
        # 4. Cleanup OTP - to prevent reuse for getting another token? 
        # Or keep it until it expires? Better to delete to prevent replay.
        await self.repo.delete_otp(email, purpose="reset_password")
        
        logger.info(f"Reset token generated for {email}")
        return {"otp_token": reset_token}

    async def handle_reset_password(self, reset_token: str, new_password: str):
        logger.info("Processing reset password request")
        
        try:
            payload = decode_token(reset_token)
        except Exception as e:
            logger.warning(f"Failed to decode reset token: {e}")
            raise InvalidResetTokenError()
            
        if payload.get("type") != "password_reset":
            logger.warning("Invalid token type for password reset")
            raise InvalidResetTokenError()
            
        user_id = payload.get("sub")
        
        async with self.repo.connection.transaction():
             user = await self.repo.get_user_by_email(payload.get("email")) # Or by ID if we had get_user_by_id
             # Since we don't have get_user_by_id in repo yet (based on read file), use email from payload if available
             # or trust sub if valid. But we need current version to increment it?
             # Actually we just update.
             
             # Better: fetch user to ensure it exists and maybe check other things?
             # The payload has 'email'.
             
             # Hash new password
             hashed_pw = get_password_hash(new_password)
             
             # Update user: password + refresh_token_version
             # We need to read user to get current version? 
             # Or just increment it in SQL? Repo update_user takes specific values.
             # If we want to increment, we might need to fetch first.
             
             if not user:
                 # Try fetching by email from payload
                 email = payload.get("email")
                 user = await self.repo.get_user_by_email(email)
                 
             if not user:
                 raise UserNotFoundError()
                 
             new_version = user.refresh_token_version + 1
             
             updates = UserUpdateSchema(
                 hashed_password=hashed_pw,
                 refresh_token_version=new_version,
                 password_changed_at=datetime.now(timezone.utc),
                 is_verified=True
             )
             
             await self.repo.update_user(user.id, updates)
             logger.info(f"Password reset successfully for user {user.id}")

    async def handle_change_password(self, user_id: str, old_password: str, new_password: str):
        logger.info(f"Change password attempt for user {user_id}")
        
        async with self.repo.connection.transaction():
            # 1. Get User
            user = await self.repo.get_user_by_id(user_id)
            if not user:
                logger.error(f"User not found during change password: {user_id}")
                raise UserNotFoundError()
                
            # 2. Verify Old Password
            if not verify_password(old_password, user.hashed_password):
                logger.warning(f"Invalid old password for user {user_id}")
                raise InvalidPasswordError()
                
            # 3. Hash New Password
            hashed_pw = get_password_hash(new_password)
            
            # 4. Update User (Password + Token Version + Timestamps)
            new_version = user.refresh_token_version + 1
            curr_time = datetime.now(timezone.utc)
            
            updates = UserUpdateSchema(
                hashed_password=hashed_pw,
                refresh_token_version=new_version,
                password_changed_at=curr_time,
                updated_at=curr_time
            )
            
            await self.repo.update_user(user.id, updates)
            
            # Note: We don't explicitly revoke tokens in refresh_tokens table here 
            # because the version increment invalidates them logicially during usage.
            # However, if immediate revocation is required, we could call revoke_all_tokens_for_user.
            
            logger.info(f"Password changed successfully for user {user_id}")