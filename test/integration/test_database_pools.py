"""集成测试 — 使用 testcontainer 验证 Redis + Postgres 连接池。"""

import pytest
from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer

from app.core.config import PostgresConfig, RedisConfig


@pytest.fixture(scope="module")
def redis_container():
    with RedisContainer("redis:7-alpine") as container:
        yield container


@pytest.fixture(scope="module")
def postgres_container():
    with PostgresContainer("postgres:16-alpine") as container:
        yield container


@pytest.fixture
def redis_config(redis_container):
    host = redis_container.get_container_host_ip()
    port = int(redis_container.get_exposed_port(6379))
    return RedisConfig(
        host=host,
        port=port,
        db=0,
        password=None,
        max_connections=5,
    )


@pytest.fixture
def postgres_config(postgres_container):
    host = postgres_container.get_container_host_ip()
    port = int(postgres_container.get_exposed_port(5432))
    return PostgresConfig(
        host=host,
        port=port,
        database="test",
        user="test",
        password="test",
        min_pool_size=1,
        max_pool_size=5,
    )


class TestRedisPool:
    """Redis 连接池集成测试。"""

    @pytest.mark.asyncio
    async def test_init_and_close(self, redis_config):
        from app.core.redis import close_redis_pool, init_redis_pool

        pool = await init_redis_pool(redis_config)
        assert await pool.ping()
        await close_redis_pool(pool)

    @pytest.mark.asyncio
    async def test_basic_operations(self, redis_config):
        from app.core.redis import close_redis_pool, init_redis_pool

        pool = await init_redis_pool(redis_config)
        try:
            await pool.set("test_key", "test_value")
            value = await pool.get("test_key")
            assert value == "test_value"

            await pool.delete("test_key")
            value = await pool.get("test_key")
            assert value is None
        finally:
            await close_redis_pool(pool)

    @pytest.mark.asyncio
    async def test_health_check(self, redis_config):
        from app.core.redis import check_redis_health, close_redis_pool, init_redis_pool

        pool = await init_redis_pool(redis_config)
        try:
            assert await check_redis_health(pool) is True
        finally:
            await close_redis_pool(pool)


class TestPostgresPool:
    """Postgres 连接池集成测试。"""

    @pytest.mark.asyncio
    async def test_init_and_close(self, postgres_config):
        from app.core.postgres import close_postgres_pool, init_postgres_pool

        pool = await init_postgres_pool(postgres_config)
        async with pool.acquire() as conn:
            result = await conn.fetchval("SELECT 1")
            assert result == 1
        await close_postgres_pool(pool)

    @pytest.mark.asyncio
    async def test_basic_operations(self, postgres_config):
        from app.core.postgres import close_postgres_pool, get_postgres_connection, init_postgres_pool

        pool = await init_postgres_pool(postgres_config)
        try:
            async for conn in get_postgres_connection(pool):
                await conn.execute(
                    "CREATE TABLE IF NOT EXISTS test_table (id SERIAL PRIMARY KEY, name TEXT)"
                )
                await conn.execute("INSERT INTO test_table (name) VALUES ($1)", "hello")
                row = await conn.fetchrow("SELECT name FROM test_table WHERE name = $1", "hello")
                assert row["name"] == "hello"
                await conn.execute("DROP TABLE test_table")
        finally:
            await close_postgres_pool(pool)

    @pytest.mark.asyncio
    async def test_health_check(self, postgres_config):
        from app.core.postgres import check_postgres_health, close_postgres_pool, init_postgres_pool

        pool = await init_postgres_pool(postgres_config)
        try:
            assert await check_postgres_health(pool) is True
        finally:
            await close_postgres_pool(pool)
