import pytest
from httpx import AsyncClient
from redis.asyncio import Redis
from unittest.mock import patch, AsyncMock

# Reuse Mock for email task
@pytest.fixture(autouse=True)
def mock_email_task_e2e():
    with patch("app.auth_service.auth_service.send_email_task.kiq", new_callable=AsyncMock) as mock:
        yield mock

@pytest.mark.asyncio
async def test_full_auth_flow_e2e(client: AsyncClient, redis_client: Redis):
    # 1. Signup
    email = "e2e_user@example.com"
    password = "password123"
    nickname = "E2E User"
    
    response = await client.post("/api/v1/auth/signup", json={
        "email": email,
        "password": password,
        "nickname": nickname
    })
    assert response.status_code == 200
    
    # 2. Get OTP (Simulate checking email)
    key = f"auth:otp:signup:{email}"
    otp = await redis_client.get(key)
    assert otp is not None
    code = otp.decode()
    
    # 3. Verify Email
    response = await client.post("/api/v1/auth/verify-email", json={
        "email": email,
        "code": code
    })
    assert response.status_code == 200
    verify_data = response.json()
    assert "access_token" in verify_data
    
    # 4. Login (End of flow)
    response = await client.post("/api/v1/auth/login", json={
        "email": email,
        "password": password
    })
    assert response.status_code == 200
    login_data = response.json()
    assert "access_token" in login_data
    assert "refresh_token" in login_data
    
    # Compare tokens (Optional, they should be different usually)
    assert login_data["access_token"] != verify_data["access_token"]
