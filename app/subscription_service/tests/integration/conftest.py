import os
import pytest
import pytest_asyncio
import uuid

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from testcontainers.postgres import PostgresContainer

from app.core.model import Base
from app.subscription_service.core.model import UserSubscriptions, UserCreditBalance, UsageLedger
from app.subscription_service.subscription_repo import SubscriptionRepo

@pytest_asyncio.fixture(scope="session")
async def postgres_container():
    with PostgresContainer("postgres:15-alpine") as postgres:
        os.environ["PG_HOST"] = postgres.get_container_host_ip()
        os.environ["PG_PORT"] = str(postgres.get_exposed_port(5432))
        os.environ["PG_USER"] = postgres.username
        os.environ["PG_PASSWORD"] = postgres.password
        os.environ["PG_DATABASE"] = postgres.dbname
        yield postgres

@pytest_asyncio.fixture(scope="function")
async def db_engine(postgres_container):
    # testcontainers provides sync url like postgresql+psycopg2://
    # We need to change it to postgresql+asyncpg://
    dsn = postgres_container.get_connection_url().replace("postgresql+psycopg2://", "postgresql+asyncpg://")
    engine = create_async_engine(dsn, echo=True)

    # Initialize DB (Schema)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine
    await engine.dispose()

@pytest_asyncio.fixture(scope="function")
async def db_session(db_engine):
    # Clean up tables before each test rather than after
    # to avoid interference from rolled-back or failed sessions within the test.
    async with db_engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(table.delete())

    async_session = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session() as session:
        yield session

@pytest.fixture
def repo(db_session):
    return SubscriptionRepo(session=db_session)

