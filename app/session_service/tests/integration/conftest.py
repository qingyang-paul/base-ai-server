import os
import pytest
import pytest_asyncio
import uuid
from unittest.mock import AsyncMock

from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from redis.asyncio import Redis

from app.core.model import Base
import app.session_service.core.model  # ensure models are registered
import app.subscription_service.core.model # for UserSubscriptions

from app.session_service.session_repo import SessionRepo
from app.session_service.session_service import SessionService
from app.chat_service.chat_service import ChatService
from app.main import app
from app.dependencies import get_db_session, get_redis, get_current_user_id
from httpx import AsyncClient, ASGITransport


@pytest_asyncio.fixture(scope="session")
async def postgres_container():
    with PostgresContainer("postgres:15-alpine") as postgres:
        os.environ["PG_HOST"] = postgres.get_container_host_ip()
        os.environ["PG_PORT"] = str(postgres.get_exposed_port(5432))
        os.environ["PG_USER"] = postgres.username
        os.environ["PG_PASSWORD"] = postgres.password
        os.environ["PG_DATABASE"] = postgres.dbname
        yield postgres

@pytest_asyncio.fixture(scope="session")
async def redis_container():
    with RedisContainer("redis:7-alpine") as redis:
        os.environ["REDIS_HOST"] = redis.get_container_host_ip()
        os.environ["REDIS_PORT"] = str(redis.get_exposed_port(6379))
        yield redis

@pytest_asyncio.fixture(scope="function")
async def db_engine(postgres_container):
    dsn = postgres_container.get_connection_url().replace("postgresql+psycopg2://", "postgresql+asyncpg://")
    engine = create_async_engine(dsn, echo=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine
    await engine.dispose()

@pytest_asyncio.fixture(scope="function")
async def db_session(db_engine):
    async_session = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session

    # Truncate tables after test using a fresh connection
    async with db_engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(table.delete())

@pytest_asyncio.fixture(scope="function")
async def redis_client(redis_container):
    client = Redis.from_url(f"redis://{redis_container.get_container_host_ip()}:{redis_container.get_exposed_port(6379)}")
    await client.flushdb()
    yield client
    await client.close()

@pytest.fixture
def mock_chat_service():
    mock_service = AsyncMock(spec=ChatService)
    
    async def mock_chat_stream(*args, **kwargs):
        from app.chat_service.core.schema import MessageChunkEvent, RunFinishEvent, StreamEventType, RoleType, LLMMessage
        yield MessageChunkEvent(
            seq_id=1,
            content="Hello AI",
        )
        yield RunFinishEvent(
            seq_id=2,
            generated_messages=[LLMMessage(role=RoleType.ASSISTANT, content="Hello AI")]
        )
        
    mock_service.chat_stream_with_tools = mock_chat_stream
    return mock_service

@pytest.fixture
def repo(db_session, redis_client):
    return SessionRepo(redis_client=redis_client, db_session=db_session)

@pytest.fixture
def session_service(repo, mock_chat_service):
    return SessionService(repo=repo, chat_service=mock_chat_service)

@pytest_asyncio.fixture(scope="function")
async def client(db_session, redis_client):
    async def override_get_db_session():
        yield db_session
        
    app.dependency_overrides[get_db_session] = override_get_db_session
    app.dependency_overrides[get_redis] = lambda: redis_client
    app.dependency_overrides[get_current_user_id] = lambda: str(uuid.uuid4())
    
    # Activate lifespan
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac
    
    app.dependency_overrides.clear()
    
@pytest_asyncio.fixture(autouse=True)
async def patch_session_service_in_app(mock_chat_service, repo):
    # This ensures that when the API route requests SessionService,
    # it gets one that uses our mocked ChatService.
    async def override_get_session_service():
        return SessionService(repo=repo, chat_service=mock_chat_service)
        
    from app.dependencies import get_session_service
    app.dependency_overrides[get_session_service] = override_get_session_service
    yield
    app.dependency_overrides.pop(get_session_service, None)
