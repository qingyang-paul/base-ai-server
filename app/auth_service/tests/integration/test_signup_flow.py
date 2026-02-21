import pytest
from sqlalchemy import text
import logging
from unittest.mock import patch, AsyncMock

# Configure logger to output to stdout even if captured
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@pytest.mark.asyncio
async def test_signup_flow_integration(client, db_session, redis_client):
    """
    Integration test for Signup Flow using global mock for email task.
    """
    
    email = "integration@example.com"
    password = "securepassword"
    
    logger.info(f"--- Starting Signup for {email} ---")
    
    response = await client.post("/api/v1/auth/signup", json={
        "email": email,
        "password": password,
        "nickname": "IntegrationUser"
    })
    
    logger.info(f"Response Status: {response.status_code}")
    
    assert response.status_code == 200
    assert response.json()["msg"] == "success"
    
    # Verify DB
    row = (await db_session.execute(text("SELECT * FROM users_auth_info WHERE email = :email"), {"email": email})).mappings().first()
    assert row is not None
    logger.info(f"User found in DB: {dict(row)}")
    assert row["email"] == email
    assert row["nick_name"] == "IntegrationUser"
    assert row["is_verified"] is False
    
    # Verify Redis OTP
    keys = await redis_client.keys(f"auth:otp:signup:{email}")
    assert len(keys) > 0
    otp = await redis_client.get(keys[0])
    logger.info(f"OTP found in Redis: {otp}")
    assert otp is not None
    
    # Verify Task Dispatch (using the global mock from conftest)
    from app.auth_service.auth_service import send_email_task
    # send_email_task.kiq is the mock object because of conftest patch
    # We can't easily access the fixture instance here unless we request it, 
    # but the patch is on the object.
    
    # However, 'send_email_task.kiq' on the IMPORTED object might not be the mock if the patch was applied on 'app.auth_service.auth_service.send_email_task.kiq'
    # and we import it from 'app.auth_service.auth_service'.
    
    # Let's verify.
    assert isinstance(send_email_task.kiq, AsyncMock) or hasattr(send_email_task.kiq, "assert_called")
    send_email_task.kiq.assert_called()
    logger.info("Email task dispatch verified.")
