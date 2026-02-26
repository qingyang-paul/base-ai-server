import os
import pytest
import pytest_asyncio
import uuid

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
def repo(db_session, redis_client):
    return SessionRepo(redis_client=redis_client, db_session=db_session)

@pytest_asyncio.fixture(scope="function")
async def client(db_session, redis_client):
    async def override_get_db_session():
        yield db_session
        
    app.dependency_overrides[get_db_session] = override_get_db_session
    app.dependency_overrides[get_redis] = lambda: redis_client
    
    # We create a stable user_id for tests
    test_user_id = str(uuid.uuid4())
    app.dependency_overrides[get_current_user_id] = lambda: test_user_id
    
    # We ALSO need to seed the `UserSubscriptions` table so `get_current_user_id` permissions pass
    from app.subscription_service.core.model import UserSubscriptions
    from datetime import datetime, timezone, timedelta
    async with db_session.begin():
        db_session.add(UserSubscriptions(
            user_id=uuid.UUID(test_user_id),
            subscription_tier="pro",
            status="active",
            current_period_start=datetime.now(timezone.utc),
            current_period_end=datetime.now(timezone.utc) + timedelta(days=30),
            auto_renew=True
        ))
    
    # Activate lifespan so LLM Client Manager starts up
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            ac.test_user_id = test_user_id
            yield ac
    
    app.dependency_overrides.clear()
