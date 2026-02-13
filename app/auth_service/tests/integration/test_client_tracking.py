import pytest
import uuid
from httpx import AsyncClient
from app.auth_service.core.security import decode_token

@pytest.mark.asyncio
async def test_client_tracking_persistence(client: AsyncClient, db_connection, redis_client):
    """
    Verify IP and Device Name persistence in Login and Refresh flows.
    """
    # 1. Signup (Standard Setup)
    email = f"track_{uuid.uuid4()}@example.com"
    password = "StrongPassword123!"
    
    await client.post("/api/v1/auth/signup", json={
        "email": email,
        "password": password, 
        "nickname": "TrackingUser"
    })
    
    # Get OTP & Verify
    otp_key = f"auth:otp:signup:{email}"
    otp_bytes = await redis_client.get(otp_key)
    if not otp_bytes:
         keys = await redis_client.keys(f"*{email}*")
         if keys: otp_bytes = await redis_client.get(keys[0])
    otp = otp_bytes.decode()
    
    await client.post("/api/v1/auth/verify-email", json={"email": email, "code": otp})

    # 2. Login with Specific Headers
    test_ip = "203.0.113.1"
    test_ua = "TestBrowser/1.0"
    
    headers = {
        "X-Forwarded-For": test_ip,
        "User-Agent": test_ua
    }
    
    login_resp = await client.post("/api/v1/auth/login", json={
        "email": email,
        "password": password
    }, headers=headers)
    
    assert login_resp.status_code == 200
    tokens = login_resp.json()
    refresh_token = tokens["refresh_token"]
    
    # Verify DB Persistence for Login
    payload = decode_token(refresh_token)
    jti = payload["jti"]
    
    row = await db_connection.fetchrow("SELECT ip_address, device_name FROM refresh_tokens WHERE jti = $1", jti)
    assert row["ip_address"] == test_ip
    assert row["device_name"] == test_ua
    
    # 3. Refresh with DIFFERENT Headers
    new_ip = "198.51.100.2"
    new_ua = "MobileApp/2.0"
    
    refresh_headers = {
        "X-Forwarded-For": new_ip,
        "User-Agent": new_ua
    }
    
    refresh_resp = await client.post("/api/v1/auth/refresh", json={
        "refresh_token": refresh_token
    }, headers=refresh_headers)
    
    assert refresh_resp.status_code == 200
    new_tokens = refresh_resp.json()
    new_refresh_token = new_tokens["refresh_token"]
    
    # Verify DB Persistence for Refresh
    new_payload = decode_token(new_refresh_token)
    new_jti = new_payload["jti"]
    
    new_row = await db_connection.fetchrow("SELECT ip_address, device_name FROM refresh_tokens WHERE jti = $1", new_jti)
    assert new_row["ip_address"] == new_ip
    assert new_row["device_name"] == new_ua
