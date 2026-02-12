import pytest
from httpx import AsyncClient
from httpx import AsyncClient
from redis.asyncio import Redis
from unittest.mock import patch, AsyncMock

@pytest.fixture(autouse=True)
def mock_email_task():
    with patch("app.auth_service.auth_service.send_email_task.kiq", new_callable=AsyncMock) as mock:
        yield mock

@pytest.mark.asyncio
async def test_login_flow(client: AsyncClient, redis_client: Redis):
    email = "login_user@example.com"
    password = "password123"
    
    # 1. Signup & Verify (Prerequisite)
    signup_payload = {"email": email, "password": password, "nickname": "LoginTest"}
    response = await client.post("/api/v1/auth/signup", json=signup_payload)
    assert response.status_code == 200 # Ensure signup success
    
    key = f"auth:otp:signup:{email}"
    otp = await redis_client.get(key)
    assert otp is not None
    code = otp.decode()
    
    verify_response = await client.post("/api/v1/auth/verify-email", json={"email": email, "code": code})
    assert verify_response.status_code == 200
    
    # 2. Login - Success
    login_payload = {"email": email, "password": password}
    response = await client.post("/api/v1/auth/login", json=login_payload)
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"
    
    # 3. Login - Invalid Password
    response = await client.post("/api/v1/auth/login", json={"email": email, "password": "wrongpassword"})
    assert response.status_code == 401
    
    # 4. Login - Invalid Email
    response = await client.post("/api/v1/auth/login", json={"email": "wrong@example.com", "password": password})
    assert response.status_code == 404

@pytest.mark.asyncio
async def test_login_unverified_email(client: AsyncClient, redis_client: Redis):
    email = "unverified@example.com"
    password = "password123"
    
    # 1. Signup only
    await client.post("/api/v1/auth/signup", json={"email": email, "password": password})
    
    # 2. Login - Should fail
    response = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 403
    assert "Email not verified" in response.json()["detail"]
