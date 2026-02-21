import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime

from app.auth_service.auth_service import AuthService
from app.auth_service.core.exceptions import (
    UserNotFoundError, 
    InvalidPasswordError, 
    EmailNotVerifiedError, 
    AccountLockedError
)
from app.auth_service.core.schema import UserInternalSchema, UserUpdateSchema

@pytest.fixture
def mock_repo():
    repo = AsyncMock()
    connection_mock = MagicMock()
    transaction_mock = MagicMock()
    transaction_mock.__aenter__ = AsyncMock(return_value=None)
    transaction_mock.__aexit__ = AsyncMock(return_value=None)
    repo.transaction = MagicMock(return_value=transaction_mock)
    
    return repo

@pytest.fixture
def mock_user():
    return UserInternalSchema(
        id="123e4567-e89b-12d3-a456-426614174000",
        email="test@example.com",
        hashed_password="hashed_secret",
        is_verified=True,
        is_active=True,
        role="user",
        refresh_token_version=1,
        created_at=datetime.now(),
        updated_at=datetime.now(),
        last_login_at=None
    )

@pytest.mark.asyncio
async def test_handle_login_success(mock_repo, mock_user):
    mock_repo.get_user_by_email.return_value = mock_user
    
    with patch("app.auth_service.auth_service.verify_password", return_value=True):
        service = AuthService(mock_repo)
        tokens = await service.handle_login("test@example.com", "secret", "127.0.0.1", "pytest")
        
        assert "access_token" in tokens
        assert "refresh_token" in tokens
        
        # Verify Repo interactions
        mock_repo.get_user_by_email.assert_called_with("test@example.com")
        mock_repo.update_user.assert_called_once()
        mock_repo.create_refresh_token.assert_called_once()
        
        # Check argument passed to create_refresh_token
        call_args = mock_repo.create_refresh_token.call_args
        token_data = call_args[0][0]
        assert token_data["user_id"] == str(mock_user.id)
        assert token_data["ip_address"] == "127.0.0.1"
        assert token_data["device_name"] == "pytest"

@pytest.mark.asyncio
async def test_handle_login_user_not_found(mock_repo):
    mock_repo.get_user_by_email.return_value = None
    
    service = AuthService(mock_repo)
    with pytest.raises(UserNotFoundError):
        await service.handle_login("unknown@example.com", "secret")

@pytest.mark.asyncio
async def test_handle_login_invalid_password(mock_repo, mock_user):
    mock_repo.get_user_by_email.return_value = mock_user
    
    with patch("app.auth_service.auth_service.verify_password", return_value=False):
        service = AuthService(mock_repo)
        with pytest.raises(InvalidPasswordError):
            await service.handle_login("test@example.com", "wrong_password")

@pytest.mark.asyncio
async def test_handle_login_email_not_verified(mock_repo, mock_user):
    mock_user.is_verified = False
    mock_repo.get_user_by_email.return_value = mock_user
    
    with patch("app.auth_service.auth_service.verify_password", return_value=True):
        service = AuthService(mock_repo)
        with pytest.raises(EmailNotVerifiedError):
            await service.handle_login("test@example.com", "secret")

@pytest.mark.asyncio
async def test_handle_login_account_locked(mock_repo, mock_user):
    mock_user.is_active = False
    mock_repo.get_user_by_email.return_value = mock_user
    
    with patch("app.auth_service.auth_service.verify_password", return_value=True):
        service = AuthService(mock_repo)
        with pytest.raises(AccountLockedError):
            await service.handle_login("test@example.com", "secret")
