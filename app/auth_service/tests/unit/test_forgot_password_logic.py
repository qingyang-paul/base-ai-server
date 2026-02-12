import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.auth_service.auth_service import AuthService
from app.auth_service.core.exceptions import OTPRateLimitError, InvalidOTPError, UserNotFoundError, InvalidResetTokenError
from app.auth_service.core.schema import UserInternalSchema, UserUpdateSchema

@pytest.mark.asyncio
async def test_handle_forgot_password_success():
    repo_mock = AsyncMock()
    repo_mock.get_user_by_email.return_value = MagicMock(spec=UserInternalSchema)
    repo_mock.get_otp_ttl.return_value = -2
    
    with patch("app.auth_service.auth_service.send_email_task") as task_mock:
        task_mock.kiq = AsyncMock()
        service = AuthService(repo_mock)
        await service.handle_forgot_password("test@example.com")
        
        repo_mock.save_otp.assert_called_once()
        task_mock.kiq.assert_called_once()

@pytest.mark.asyncio
async def test_handle_forgot_password_rate_limit():
    repo_mock = AsyncMock()
    repo_mock.get_user_by_email.return_value = MagicMock(spec=UserInternalSchema)
    repo_mock.get_otp_ttl.return_value = 250
    
    service = AuthService(repo_mock)
    with pytest.raises(OTPRateLimitError):
        await service.handle_forgot_password("test@example.com")

@pytest.mark.asyncio
async def test_verify_reset_code_success():
    repo_mock = AsyncMock()
    repo_mock.get_otp.return_value = "123456"
    
    user = MagicMock(spec=UserInternalSchema)
    user.id = "uuid"
    user.email = "test@example.com"
    repo_mock.get_user_by_email.return_value = user
    
    service = AuthService(repo_mock)
    result = await service.handle_verify_reset_code("test@example.com", "123456")
    
    assert "otp_token" in result
    repo_mock.delete_otp.assert_called_once()

@pytest.mark.asyncio
async def test_reset_password_success():
    repo_mock = AsyncMock()
    
    # Mock transaction
    connection_mock = MagicMock()
    transaction_mock = AsyncMock()
    transaction_mock.__aenter__.return_value = None
    transaction_mock.__aexit__.return_value = None
    connection_mock.transaction.return_value = transaction_mock
    repo_mock.connection = connection_mock

    # Mock user
    user = MagicMock(spec=UserInternalSchema)
    user.id = "uuid"
    user.refresh_token_version = 1
    repo_mock.get_user_by_email.return_value = user # Called inside handle_reset_password if payload has email or from sub
    
    service = AuthService(repo_mock)
    
    # Generate a valid token for testing
    from app.auth_service.core.security import create_token
    from datetime import timedelta
    token = create_token({
        "sub": "uuid", 
        "email": "test@example.com", 
        "type": "password_reset"
    }, expires_delta=timedelta(minutes=10))
    
    await service.handle_reset_password(token, "newpassword")
    
    repo_mock.update_user.assert_called_once()
    args, _ = repo_mock.update_user.call_args
    assert args[0] == "uuid"
    assert args[1].refresh_token_version == 2
    assert args[1].hashed_password is not None
