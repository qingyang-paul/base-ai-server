import os
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

# Generate dummy keys for testing
fernet_key = Fernet.generate_key().decode()
private_key = rsa.generate_private_key(
    public_exponent=65537,
    key_size=2048,
)
private_pem = private_key.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption()
).decode()
public_key = private_key.public_key()
public_pem = public_key.public_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PublicFormat.SubjectPublicKeyInfo
).decode()

# Set environment variables
os.environ["JWT_PRIVATE_KEY"] = private_pem
os.environ["JWT_PUBLIC_KEY"] = public_pem
os.environ["SECURITY_ENCRYPTION_KEY"] = fernet_key
os.environ["ACCESS_TOKEN_EXPIRE_MINUTES"] = "30"
os.environ["REFRESH_TOKEN_EXPIRE_DAYS"] = "7"
os.environ["SECURITY_PASSWORD_HASH_ROUNDS"] = "4"
os.environ["OTEL_SERVICE_NAME"] = "test-service"
os.environ["OTEL_EXPORTER_ENDPOINT"] = "http://localhost:4317"
os.environ["OTEL_INSECURE"] = "true"
os.environ["LOG_JSON_FORMAT"] = "false"
os.environ["REDIS_HOST"] = "localhost"
os.environ["REDIS_PORT"] = "6379"
os.environ["REDIS_DB"] = "0"
os.environ["REDIS_MAX_CONNECTIONS"] = "10"
os.environ["PG_HOST"] = "localhost"
os.environ["PG_PORT"] = "5432"
os.environ["PG_DATABASE"] = "test"
os.environ["PG_USER"] = "test"
os.environ["PG_PASSWORD"] = "test"
os.environ["PG_MIN_POOL_SIZE"] = "1"
os.environ["PG_MAX_POOL_SIZE"] = "10"

import pytest
import pytest_asyncio
import asyncpg
from httpx import AsyncClient, ASGITransport
from redis.asyncio import Redis
from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer

from app.main import app
from app.main import app
from app.dependencies import get_postgres, get_redis
from unittest.mock import patch, AsyncMock

@pytest_asyncio.fixture(scope="function", autouse=True)
async def mock_email_task():
    with patch("app.auth_service.auth_service.send_email_task.kiq", new_callable=AsyncMock) as mock:
        yield mock

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
async def db_pool(postgres_container):
    # Create asyncpg pool
    dsn = postgres_container.get_connection_url().replace("postgresql+psycopg2://", "postgres://")
    pool = await asyncpg.create_pool(dsn)
    
    # Initialize DB (Schema)
    # Since we removed SQLAlchemy, we need to create tables using raw SQL or migration tool.
    # We need the table `users_auth_info`.
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users_auth_info (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                email VARCHAR(255) UNIQUE NOT NULL,
                hashed_password VARCHAR(255) NOT NULL,
                nick_name VARCHAR(255),
                is_verified BOOLEAN DEFAULT FALSE,
                is_active BOOLEAN DEFAULT TRUE,
                role VARCHAR(50) DEFAULT 'user',
                refresh_token_version INTEGER DEFAULT 0,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                last_login_at TIMESTAMP WITH TIME ZONE,
                password_changed_at TIMESTAMP WITH TIME ZONE
            );
            
            CREATE TABLE IF NOT EXISTS refresh_tokens (
                jti VARCHAR(255) PRIMARY KEY,
                user_id UUID NOT NULL,
                family_id VARCHAR(255),
                parent_jti VARCHAR(255),
                token_version INTEGER,
                revoked_at TIMESTAMP WITH TIME ZONE,
                replaced_at TIMESTAMP WITH TIME ZONE,
                expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                ip_address VARCHAR(255),
                device_name VARCHAR(255)
            );
        """)
    
    yield pool
    await pool.close()

@pytest_asyncio.fixture(scope="function")
async def db_connection(db_pool):
    async with db_pool.acquire() as conn:
        # Start transaction for rollback?
        tr = conn.transaction()
        await tr.start()
        yield conn
        await tr.rollback()

@pytest_asyncio.fixture(scope="function")
async def redis_client(redis_container):
    client = Redis.from_url(f"redis://{redis_container.get_container_host_ip()}:{redis_container.get_exposed_port(6379)}")
    await client.flushdb()
    yield client
    await client.close()


@pytest_asyncio.fixture(scope="function")
async def client(db_connection, redis_client):
    app.dependency_overrides[get_postgres] = lambda: db_connection
    app.dependency_overrides[get_redis] = lambda: redis_client
    
    # Activate lifespan for FastAPILimiter and other startup events
    # We must use the app instance to trigger its lifespan
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac
    
    app.dependency_overrides.clear()
