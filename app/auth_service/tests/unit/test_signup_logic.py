import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.auth_service.auth_service import AuthService
from app.auth_service.core.exceptions import DuplicateEmailError, OTPRateLimitError, InvalidOTPError
from app.auth_service.core.schema import UserInternalSchema, UserUpdateSchema

@pytest.mark.asyncio
async def test_handle_signup_new_user():
    repo_mock = AsyncMock()
    repo_mock.get_otp_ttl.return_value = -2 # No existing OTP
    repo_mock.get_user_by_email.return_value = None
    
    # Configure connection mock
    connection_mock = MagicMock()
    # fetchrow and execute are async
    connection_mock.fetchrow = AsyncMock()
    connection_mock.execute = AsyncMock()
    # transaction is sync, returns async context manager
    transaction_mock = AsyncMock()
    transaction_mock.__aenter__.return_value = None
    transaction_mock.__aexit__.return_value = None
    connection_mock.transaction.return_value = transaction_mock
    
    repo_mock.connection = connection_mock
    
    with patch("app.auth_service.auth_service.send_email_task") as task_mock:
        task_mock.kiq = AsyncMock()
        
        service = AuthService(repo_mock)
        await service.handle_signup("test@example.com", "password")
        
        repo_mock.create_user.assert_called_once()
        repo_mock.save_otp.assert_called_once()
        task_mock.kiq.assert_called_once()
        # Ensure kig was called with correct args (no trace_id)
        # Call args: (email, subject, content)
        args, kwargs = task_mock.kiq.call_args
        assert args[0] == "test@example.com"
        # Verify transaction was entered
        connection_mock.transaction.assert_called_once()
        transaction_mock.__aenter__.assert_called_once()

@pytest.mark.asyncio
async def test_handle_signup_rate_limit():
    repo_mock = AsyncMock()
    repo_mock.get_otp_ttl.return_value = 290 # Created 10s ago
    
    # Configure connection mock (needed because it's accessed before exception?)
    # Actually exception happens before transaction in this logic
    # But good practice to mock
    connection_mock = MagicMock()
    transaction_mock = AsyncMock()
    connection_mock.transaction.return_value = transaction_mock
    repo_mock.connection = connection_mock
    
    service = AuthService(repo_mock)
    
    with pytest.raises(OTPRateLimitError):
        await service.handle_signup("test@example.com", "password")

@pytest.mark.asyncio
async def test_verify_email_success():
    repo_mock = AsyncMock()
    repo_mock.get_otp.return_value = "123456"
    
    # Configure connection mock
    connection_mock = MagicMock()
    transaction_mock = AsyncMock()
    transaction_mock.__aenter__.return_value = None
    transaction_mock.__aexit__.return_value = None
    connection_mock.transaction.return_value = transaction_mock
    repo_mock.connection = connection_mock

    user = MagicMock(spec=UserInternalSchema)
    user.id = "uuid"
    user.role = "user"
    user.refresh_token_version = 1
    # is_verified on UserInternalSchema
    user.is_verified = False
    repo_mock.get_user_by_email.return_value = user
    
    service = AuthService(repo_mock)
    tokens = await service.handle_verify_email("test@example.com", "123456")
    
    assert "access_token" in tokens
    assert "refresh_token" in tokens
    
    # Verify updates: update_user(user.id, UserUpdateSchema(is_verified=True))
    repo_mock.update_user.assert_called_once()
    args, _ = repo_mock.update_user.call_args
    assert args[0] == "uuid"
    assert isinstance(args[1], UserUpdateSchema)
    assert args[1].is_verified is True
    
    repo_mock.delete_otp.assert_called_once()
    transaction_mock.__aenter__.assert_called_once()

@pytest.mark.asyncio
async def test_verify_email_invalid_code():
    repo_mock = AsyncMock()
    repo_mock.get_otp.return_value = "654321" # Different code
    
    connection_mock = MagicMock()
    transaction_mock = AsyncMock()
    connection_mock.transaction.return_value = transaction_mock
    repo_mock.connection = connection_mock
    
    service = AuthService(repo_mock)
    
    with pytest.raises(InvalidOTPError):
        await service.handle_verify_email("test@example.com", "123456")
