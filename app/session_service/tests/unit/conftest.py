import pytest
from unittest.mock import AsyncMock, MagicMock
from app.session_service.session_repo import SessionRepo
from app.chat_service.chat_service import ChatService
from app.session_service.session_service import SessionService

@pytest.fixture
def mock_redis():
    redis = AsyncMock()
    # Mock pipeline
    pipeline_mock = MagicMock()
    pipeline_mock.execute = AsyncMock()
    redis.pipeline = MagicMock(return_value=pipeline_mock)
    return redis

@pytest.fixture
def mock_db():
    return AsyncMock()

@pytest.fixture
def mock_repo(mock_redis, mock_db):
    repo = SessionRepo(redis_client=mock_redis, db_session=mock_db)
    # mock some smart methods if needed for service testing later,
    # but for repo testing, we use the raw mock_redis and mock_db
    return repo

@pytest.fixture
def mock_chat_service():
    return AsyncMock(spec=ChatService)

@pytest.fixture
def session_service(mock_repo, mock_chat_service):
    return SessionService(repo=mock_repo, chat_service=mock_chat_service)
