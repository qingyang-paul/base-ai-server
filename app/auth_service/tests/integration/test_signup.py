import pytest
from httpx import AsyncClient
from redis.asyncio import Redis

@pytest.mark.asyncio
async def test_signup_flow(client: AsyncClient, redis_client: Redis):
    # 1. Signup
    payload = {
        "email": "test@example.com",
        "password": "password123",
        "nickname": "TestUser"
    }
    response = await client.post("/api/v1/auth/signup", json=payload)
    assert response.status_code == 200
    assert response.json() == {"msg": "success"}

    # 2. Get OTP from Redis
    key = "auth:otp:signup:test@example.com"
    otp = await redis_client.get(key)
    assert otp is not None
    code = otp.decode()

    # 3. Verify Email
    verify_payload = {
        "email": "test@example.com",
        "code": code
    }
    response = await client.post("/api/v1/auth/verify-email", json=verify_payload)
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"

    # 4. Verify user allows login or is verified in DB (implicit by token issuance)

@pytest.mark.asyncio
async def test_signup_duplicate_verified(client: AsyncClient, redis_client: Redis):
    email = "duplicate@example.com"
    payload = {
        "email": email,
        "password": "password123",
        "nickname": "DuplicateUser"
    }
    
    # First signup
    await client.post("/api/v1/auth/signup", json=payload)
    key = f"auth:otp:signup:{email}"
    otp = await redis_client.get(key)
    code = otp.decode()
    await client.post("/api/v1/auth/verify-email", json={"email": email, "code": code})
    
    # Second signup (Duplicate)
    response = await client.post("/api/v1/auth/signup", json=payload)
    assert response.status_code == 400
    assert "already registered" in response.json()["detail"]

@pytest.mark.asyncio
async def test_rate_limit_otp(client: AsyncClient):
    email = "ratelimit@example.com"
    payload = {
        "email": email,
        "password": "password123"
    }
    
    # First Request
    response = await client.post("/api/v1/auth/signup", json=payload)
    assert response.status_code == 200
    
    # Second Request immediately
    response = await client.post("/api/v1/auth/signup", json=payload)
    assert response.status_code == 429
    assert "too frequent" in response.json()["detail"]
