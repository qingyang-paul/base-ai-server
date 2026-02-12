import pytest
import logging
from unittest.mock import patch
from taskiq import InMemoryBroker

from app.auth_service.core.schema import UserInternalSchema

# Configure logger to output to stdout even if captured
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@pytest.fixture
def mock_smtp():
    with patch("aiosmtplib.send") as mock:
        mock.return_value = ({}, "OK")
        yield mock

@pytest.mark.asyncio
async def test_signup_flow_integration(client, db_connection, redis_client, mock_smtp):
    """
    Integration test for Signup Flow.
    Uses:
    - PostgresContainer (via db_connection)
    - RedisContainer (via redis_client)
    - InMemoryBroker (patched) to execute tasks immediately and print logs
    """
    
    # patch the broker in app.taskiq to be InMemoryBroker
    new_broker = InMemoryBroker()
    
    # We patch app.auth_service.tasks.send_email.broker via the task instance
    
    # Start the broker
    await new_broker.startup()
    
    # Force InMemoryBroker by replacing the broker on the task itself.
    from app.auth_service.tasks.send_email import send_email_task
    original_broker = send_email_task.broker
    send_email_task.broker = new_broker
    
    # CRITICAL: Register the task with the new broker so it can be passed to execution
    # InMemoryBroker needs to find the function in its registry
    new_broker.register_task(
        send_email_task.original_func,
        task_name=send_email_task.task_name
    )
    
    try:
        email = "integration@example.com"
        password = "securepassword"
        
        logger.info(f"--- Starting Signup for {email} ---")
        
        response = await client.post("/api/v1/auth/signup", json={
            "email": email,
            "password": password,
            "nickname": "IntegrationUser"
        })
        
        logger.info(f"Response Status: {response.status_code}")
        logger.info(f"Response Body: {response.json()}")
        
        assert response.status_code == 200
        assert response.json()["msg"] == "success"
        
        # Verify DB
        row = await db_connection.fetchrow("SELECT * FROM users_auth_info WHERE email = $1", email)
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
        
        # Verify Task Execution
        # Check if mock_smtp was called
        mock_smtp.assert_called()
        logger.info("Email task executed successfully (mocked SMTP).")
        
    finally:
        await new_broker.shutdown()
        send_email_task.broker = original_broker
        logger.info("--- Test Finished ---")
