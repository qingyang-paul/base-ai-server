from enum import Enum
from typing import Optional

from pydantic import BaseModel
from pydantic_settings import BaseSettings


class LoggerConfig(BaseModel):
    json_format: bool


class TelemetryConfig(BaseModel):
    service_name: str
    exporter_endpoint: str
    insecure: bool


class RedisConfig(BaseModel):
    host: str
    port: int
    db: int
    password: Optional[str]
    max_connections: int


class PostgresConfig(BaseModel):
    host: str
    port: int
    database: str
    user: str
    password: str
    min_pool_size: int
    max_pool_size: int


class WorkEnvironment(str, Enum):
    DEVELOPMENT = "development"
    TESTING = "testing"
    PRODUCTION = "production"


class Settings(BaseSettings):
    work_environment: WorkEnvironment

    log_json_format: bool
    otel_service_name: str
    otel_exporter_endpoint: str
    otel_insecure: bool

    redis_host: str
    redis_port: int
    redis_db: int
    redis_password: Optional[str] = None
    redis_max_connections: int

    pg_host: str
    pg_port: int
    pg_database: str
    pg_user: str
    pg_password: str
    pg_min_pool_size: int
    pg_max_pool_size: int

    @property
    def logger(self) -> LoggerConfig:
        return LoggerConfig(json_format=self.log_json_format)

    @property
    def telemetry(self) -> TelemetryConfig:
        return TelemetryConfig(
            service_name=self.otel_service_name,
            exporter_endpoint=self.otel_exporter_endpoint,
            insecure=self.otel_insecure,
        )

    @property
    def redis(self) -> RedisConfig:
        return RedisConfig(
            host=self.redis_host,
            port=self.redis_port,
            db=self.redis_db,
            password=self.redis_password,
            max_connections=self.redis_max_connections,
        )

    @property
    def postgres(self) -> PostgresConfig:
        return PostgresConfig(
            host=self.pg_host,
            port=self.pg_port,
            database=self.pg_database,
            user=self.pg_user,
            password=self.pg_password,
            min_pool_size=self.pg_min_pool_size,
            max_pool_size=self.pg_max_pool_size,
        )

    model_config = {"env_file": ".env", "extra": "ignore"}
