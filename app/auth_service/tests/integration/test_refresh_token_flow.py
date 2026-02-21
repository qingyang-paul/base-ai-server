import pytest
import pytest
import datetime
import uuid
from typing import Dict
from httpx import AsyncClient
from app.auth_service.core.security import decode_token
from sqlalchemy import text

@pytest.mark.asyncio
async def test_refresh_token_flow(client: AsyncClient, db_session, redis_client):

    """
    Integration test for Refresh Token Flow:
    1. Signup & Verify -> Get Tokens
    2. Refresh -> Get New Tokens (Rotation)
    3. Grace Period Reuse -> Get Valid Tokens
    4. Reuse Attack (>30s) -> Revocation
    """
    # 1. Setup User
    email = f"refresh_{uuid.uuid4()}@example.com"
    password = "StrongPassword123!"
    
    signup_resp = await client.post("/api/v1/auth/signup", json={
        "email": email,
        "password": password, 
        "nickname": "RefreshUser"
    })
    assert signup_resp.status_code == 200
    
    # Get OTP from Redis
    otp_key_prefix = "auth:otp:signup:"
    # In integration test, we might need to find the key. 
    # Since we generated email uniquely, we can construct the key.
    otp_key = f"{otp_key_prefix}{email}"
    
    # Wait for async task? 
    # Signup implementation:
    # await self.repo.save_otp(email, code, purpose="signup") -> Redis
    # The task part is for EMAIL SENDING. Redis save is synchronous in the handler (awaited).
    # So OTP should be there immediately.
    
    otp_bytes = await redis_client.get(otp_key)
    
    if otp_bytes is None:
         # Try to find by pattern
         keys = await redis_client.keys(f"*{email}*")
         if keys:
             otp_bytes = await redis_client.get(keys[0])
    
    assert otp_bytes is not None
    otp = otp_bytes.decode()
    
    # Verify Email -> Get Tokens
    verify_resp = await client.post("/api/v1/auth/verify-email", json={"email": email, "code": otp})
    assert verify_resp.status_code == 200
    tokens = verify_resp.json()
    
    # Check tokens
    access_token_1 = tokens["access_token"]
    refresh_token_1 = tokens["refresh_token"]
    assert access_token_1
    assert refresh_token_1
    
    # Verify RT_1 payload
    rt_1_payload = decode_token(refresh_token_1)
    family_id_1 = rt_1_payload.get("family_id")
    assert family_id_1
    
    # 2. Refresh Token (Normal Rotation)
    # We simulate a "Later" call.
    refresh_resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token_1})
    if refresh_resp.status_code != 200:
        print(refresh_resp.json())
        
    assert refresh_resp.status_code == 200
    tokens_2 = refresh_resp.json()
    access_token_2 = tokens_2["access_token"]
    refresh_token_2 = tokens_2["refresh_token"]
    
    # Tokens should change
    assert access_token_2 != access_token_1
    assert refresh_token_2 != refresh_token_1
    
    # Verify RT_2 payload
    rt_2_payload = decode_token(refresh_token_2)
    assert rt_2_payload["family_id"] == family_id_1
    assert rt_2_payload["jti"] != rt_1_payload["jti"]
    
    # 3. Grace Period Reuse (RT_1 again)
    # Immediate retry with old token
    reuse_resp_grace = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token_1})
    assert reuse_resp_grace.status_code == 200
    tokens_grace = reuse_resp_grace.json()
    
    # Check grace token
    # Access token should be new (stateless)
    # Refresh token should be... ? 
    # In my implementation, I return a NEW signed Refresh Token with the SAME JTI as the "Latest" one (RT_2's JTI).
    # Let's verify JTI matches RT_2
    rt_grace_payload = decode_token(tokens_grace["refresh_token"])
    assert rt_grace_payload["jti"] == rt_2_payload["jti"]
    
    # 4. Reuse Attack (RT_1 again after > 30s)
    # We need to manipulate `replaced_at` of RT_1 in DB.
    jti_1 = rt_1_payload["jti"]
    
    # Update replaced_at to 40 seconds ago
    # Use Python datetime to ensure control
    past_time = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=45)
    
    await db_session.execute(
        text("UPDATE refresh_tokens SET replaced_at = :replaced_at WHERE jti = :jti"),
        {"replaced_at": past_time, "jti": jti_1}
    )
    
    # Verify the update happened
    row = (await db_session.execute(text("SELECT replaced_at FROM refresh_tokens WHERE jti = :jti"), {"jti": jti_1})).mappings().first()
    
    # Attempt Reuse of RT_1 -> Should Fail and Revoke All
    reuse_resp_attack = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token_1})
    assert reuse_resp_attack.status_code == 400
    # Error detail might be "Invalid or expired reset token." (from exception class)
    
    # Verify All Tokens Revoked
    # Try using RT_2 (which was valid) -> Should now be invalid
    refresh_resp_3 = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token_2})
    assert refresh_resp_3.status_code == 400
    
    # Also verify user can't login? 
    # Or check DB "revoked_at" on all tokens
    # user_id is UUID in DB, but sub in token is string.
    user_id = rt_1_payload["sub"]
    
    # Check RT_2 revoked_at
    jti_2 = rt_2_payload["jti"]
    row_2 = (await db_session.execute(text("SELECT revoked_at FROM refresh_tokens WHERE jti = :jti"), {"jti": jti_2})).mappings().first()
    assert row_2["revoked_at"] is not None

