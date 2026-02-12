import pytest
import logging
from unittest.mock import AsyncMock

# Configure logger to output to stdout even if captured
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@pytest.mark.asyncio
async def test_forgot_password_flow_integration(client, db_connection, redis_client):
    """
    Integration test for Forgot Password Flow.
    """
    email = "forgot_pwd@example.com"
    old_password = "oldpassword"
    new_password = "newpassword123"
    
    # 1. Create User via Signup first (or direct DB insert)
    # Using signup endpoint to populate DB
    await client.post("/api/v1/auth/signup", json={
        "email": email,
        "password": old_password,
        "nickname": "ForgotPwdUser"
    })
    
    # 2. Request Password Reset
    logger.info(f"--- Requesting password reset for {email} ---")
    response = await client.post("/api/v1/auth/forgot-password", json={"email": email})
    assert response.status_code == 200
    
    # 3. Get OTP from Redis
    keys = await redis_client.keys(f"auth:otp:reset_password:{email}")
    assert len(keys) > 0
    otp = await redis_client.get(keys[0])
    # Decode if bytes (redis-py returns bytes usually)
    if isinstance(otp, bytes):
        otp = otp.decode()
    logger.info(f"OTP retrieved: {otp}")
    
    # 4. Verify OTP
    logger.info("--- Verifying OTP ---")
    response = await client.post("/api/v1/auth/verify-reset-code", json={"email": email, "code": otp})
    assert response.status_code == 200
    otp_token = response.json().get("otp_token")
    assert otp_token is not None
    logger.info(f"OTP Token received: {otp_token[:10]}...")
    
    # 5. Reset Password
    logger.info("--- Resetting Password ---")
    response = await client.post("/api/v1/auth/reset-password", json={
        "reset_token": otp_token,
        "new_password": new_password
    })
    assert response.status_code == 200
    assert response.json()["msg"] == "Password reset successfully."
    
    # 6. Verify Login with New Password
    logger.info("--- Verifying Login with New Password ---")
    response = await client.post("/api/v1/auth/login", json={
        "email": email,
        "password": new_password
    })
    assert response.status_code == 200
    assert "access_token" in response.json()
    
    # 7. Verify Login with Old Password (should fail)
    logger.info("--- Verifying Login with Old Password (should fail) ---")
    response = await client.post("/api/v1/auth/login", json={
        "email": email,
        "password": old_password
    })
    assert response.status_code == 401
