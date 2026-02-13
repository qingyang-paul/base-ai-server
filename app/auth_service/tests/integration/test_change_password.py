import pytest
from httpx import AsyncClient
from redis.asyncio import Redis

@pytest.mark.asyncio
async def test_change_password_flow(client: AsyncClient, redis_client: Redis):
    email = "changepw_flow@example.com"
    old_password = "OldPassword123!"
    
    # 1. Signup
    await client.post("/api/v1/auth/signup", json={
        "email": email, 
        "password": old_password,
        "nickname": "ChangePwUser"
    })
    
    # 2. Verify Email
    key = f"auth:otp:signup:{email}"
    otp_bytes = await redis_client.get(key)
    assert otp_bytes is not None
    code = otp_bytes.decode()
    
    await client.post("/api/v1/auth/verify-email", json={"email": email, "code": code})
    
    # 3. Login
    login_res = await client.post("/api/v1/auth/login", json={"email": email, "password": old_password})
    assert login_res.status_code == 200
    tokens = login_res.json()
    access_token = tokens["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}
    
    # 4. Change Password - Success
    new_password = "NewPassword456!"
    change_res = await client.post(
        "/api/v1/auth/change-password",
        json={"old_password": old_password, "new_password": new_password},
        headers=headers
    )
    assert change_res.status_code == 200
    assert change_res.json()["msg"] == "Password changed successfully"
    
    # 5. Verify Old Password Fails
    login_fail = await client.post("/api/v1/auth/login", json={"email": email, "password": old_password})
    assert login_fail.status_code == 401
    
    # 6. Verify New Password Succeeds
    login_succ = await client.post("/api/v1/auth/login", json={"email": email, "password": new_password})
    assert login_succ.status_code == 200


@pytest.mark.asyncio
async def test_change_password_invalid_old(client: AsyncClient, redis_client: Redis):
    email = "wrong_old_pw@example.com"
    password = "MyPassword123!"
    
    # Setup User
    await client.post("/api/v1/auth/signup", json={"email": email, "password": password})
    key = f"auth:otp:signup:{email}"
    otp_bytes = await redis_client.get(key)
    code = otp_bytes.decode()
    await client.post("/api/v1/auth/verify-email", json={"email": email, "code": code})
    
    # Login
    login_res = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    access_token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}
    
    # Attempt Change with Wrong Old Password
    res = await client.post(
        "/api/v1/auth/change-password",
        json={"old_password": "WrongPassword!", "new_password": "NewPw12345!"},
        headers=headers
    )
    assert res.status_code == 401
    assert res.json()["detail"] == "Invalid password."


@pytest.mark.asyncio
async def test_change_password_unauthorized(client: AsyncClient):
    res = await client.post(
        "/api/v1/auth/change-password",
        json={"old_password": "old", "new_password": "new"}
    )
    assert res.status_code == 401
