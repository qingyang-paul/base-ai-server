"""单元测试 — Config Schema 验证。"""

import os

import pytest
from pydantic import ValidationError

os.environ.setdefault("LOG_JSON_FORMAT", "true")
os.environ.setdefault("OTEL_SERVICE_NAME", "test-service")
os.environ.setdefault("OTEL_EXPORTER_ENDPOINT", "http://localhost:4317")
os.environ.setdefault("OTEL_INSECURE", "true")
os.environ.setdefault("WORK_ENVIRONMENT", "testing")
os.environ.setdefault("REDIS_HOST", "localhost")
os.environ.setdefault("REDIS_PORT", "6379")
os.environ.setdefault("REDIS_DB", "0")
os.environ.setdefault("REDIS_MAX_CONNECTIONS", "10")
os.environ.setdefault("PG_HOST", "localhost")
os.environ.setdefault("PG_PORT", "5432")
os.environ.setdefault("PG_DATABASE", "test_db")
os.environ.setdefault("PG_USER", "test_user")
os.environ.setdefault("PG_PASSWORD", "test_pass")
os.environ.setdefault("PG_MIN_POOL_SIZE", "2")
os.environ.setdefault("PG_MAX_POOL_SIZE", "10")


class TestRedisConfig:
    """RedisConfig Schema 验证。"""

    def test_valid_config(self):
        from app.core.config import RedisConfig

        config = RedisConfig(
            host="localhost",
            port=6379,
            db=0,
            password=None,
            max_connections=10,
        )
        assert config.host == "localhost"
        assert config.port == 6379
        assert config.password is None

    def test_with_password(self):
        from app.core.config import RedisConfig

        config = RedisConfig(
            host="redis.example.com",
            port=6380,
            db=1,
            password="secret",
            max_connections=20,
        )
        assert config.password == "secret"

    def test_missing_required_field(self):
        from app.core.config import RedisConfig

        with pytest.raises(ValidationError):
            RedisConfig(host="localhost", port=6379)  # type: ignore[call-arg]


class TestPostgresConfig:
    """PostgresConfig Schema 验证。"""

    def test_valid_config(self):
        from app.core.config import PostgresConfig

        config = PostgresConfig(
            host="localhost",
            port=5432,
            database="mydb",
            user="admin",
            password="secret",
            min_pool_size=2,
            max_pool_size=10,
        )
        assert config.database == "mydb"
        assert config.min_pool_size == 2

    def test_missing_required_field(self):
        from app.core.config import PostgresConfig

        with pytest.raises(ValidationError):
            PostgresConfig(host="localhost", port=5432)  # type: ignore[call-arg]


class TestSettingsProperties:
    """Settings 的 redis / postgres property 映射。"""

    def test_redis_property(self):
        from app.core.config import Settings

        settings = Settings()
        redis_config = settings.redis
        assert redis_config.host == "localhost"
        assert redis_config.port == 6379

    def test_postgres_property(self):
        from app.core.config import Settings

        settings = Settings()
        pg_config = settings.postgres
        assert pg_config.host == "localhost"
        assert pg_config.database == "test_db"


class TestExceptions:
    """异常类测试。"""

    def test_redis_connection_error(self):
        from app.core.exceptions import DatabaseConnectionError, RedisConnectionError

        exc = RedisConnectionError(detail="Connection refused")
        assert isinstance(exc, DatabaseConnectionError)
        assert exc.service == "Redis"
        assert "Connection refused" in str(exc)

    def test_postgres_connection_error(self):
        from app.core.exceptions import DatabaseConnectionError, PostgresConnectionError

        exc = PostgresConnectionError(detail="Timeout")
        assert isinstance(exc, DatabaseConnectionError)
        assert exc.service == "Postgres"

    def test_pool_exhausted_error(self):
        from app.core.exceptions import ConnectionPoolExhaustedError, DatabaseConnectionError

        exc = ConnectionPoolExhaustedError(service="Redis")
        assert isinstance(exc, DatabaseConnectionError)
        assert "exhausted" in str(exc)
