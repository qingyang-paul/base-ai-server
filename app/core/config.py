from enum import Enum

from pydantic import BaseModel
from pydantic_settings import BaseSettings


class LoggerConfig(BaseModel):
    json_format: bool


class TelemetryConfig(BaseModel):
    service_name: str
    exporter_endpoint: str
    insecure: bool


class RedisConfig(BaseModel):
    pass


class PostgresConfig(BaseModel):
    pass


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

    model_config = {"env_file": ".env", "extra": "ignore"}
