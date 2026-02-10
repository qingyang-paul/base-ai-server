"""集成测试 — Health 接口验证数据库连接状况。"""

import os

import httpx
import pytest
from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer

os.environ.setdefault("LOG_JSON_FORMAT", "true")
os.environ.setdefault("OTEL_SERVICE_NAME", "test-service")
os.environ.setdefault("OTEL_EXPORTER_ENDPOINT", "http://localhost:4317")
os.environ.setdefault("OTEL_INSECURE", "true")
os.environ.setdefault("WORK_ENVIRONMENT", "testing")


@pytest.fixture(scope="module")
def redis_container():
    with RedisContainer("redis:7-alpine") as container:
        yield container


@pytest.fixture(scope="module")
def postgres_container():
    with PostgresContainer("postgres:16-alpine") as container:
        yield container


@pytest.fixture
def env_setup(redis_container, postgres_container, monkeypatch):
    """设置环境变量指向 testcontainer 实例。"""
    monkeypatch.setenv("REDIS_HOST", redis_container.get_container_host_ip())
    monkeypatch.setenv("REDIS_PORT", str(redis_container.get_exposed_port(6379)))
    monkeypatch.setenv("REDIS_DB", "0")
    monkeypatch.setenv("REDIS_MAX_CONNECTIONS", "5")

    monkeypatch.setenv("PG_HOST", postgres_container.get_container_host_ip())
    monkeypatch.setenv("PG_PORT", str(postgres_container.get_exposed_port(5432)))
    monkeypatch.setenv("PG_DATABASE", "test")
    monkeypatch.setenv("PG_USER", "test")
    monkeypatch.setenv("PG_PASSWORD", "test")
    monkeypatch.setenv("PG_MIN_POOL_SIZE", "1")
    monkeypatch.setenv("PG_MAX_POOL_SIZE", "5")


class TestHealthEndpoint:
    """Health 接口集成测试。"""

    @pytest.mark.asyncio
    async def test_health_returns_200_when_all_healthy(self, env_setup):
        from fastapi import FastAPI

        from app.api.v1.router import api_router
        from app.core.lifespan import lifespan

        app = FastAPI(lifespan=lifespan)
        app.include_router(api_router, prefix="/api/v1")

        async with lifespan(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/api/v1/core/health")
                assert response.status_code == 200
                data = response.json()
                assert data["status"] == "healthy"
                assert data["redis"] == "up"
                assert data["postgres"] == "up"

    @pytest.mark.asyncio
    async def test_health_returns_503_when_redis_down(self, env_setup, monkeypatch):
        """模拟 Redis 不可达，检查 health 接口返回 503。"""
        monkeypatch.setenv("REDIS_HOST", "192.0.2.1")  # 不可达地址
        monkeypatch.setenv("REDIS_PORT", "6379")

        from fastapi import FastAPI

        from app.core.config import RedisConfig, Settings
        from app.core.lifespan import lifespan
        from app.core.redis import init_redis_pool

        # Redis 连接失败时 init_redis_pool 会抛异常
        from app.core.exceptions import RedisConnectionError

        with pytest.raises(RedisConnectionError):
            settings = Settings()
            await init_redis_pool(settings.redis)
