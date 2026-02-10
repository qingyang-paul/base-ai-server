import os

os.environ.setdefault("LOG_JSON_FORMAT", "true")
os.environ.setdefault("OTEL_SERVICE_NAME", "test-service")
os.environ.setdefault("OTEL_EXPORTER_ENDPOINT", "http://localhost:4317")
os.environ.setdefault("OTEL_INSECURE", "true")
os.environ.setdefault("WORK_ENVIRONMENT", "testing")


class TestTracerProviderSetup:
    """验证 OTel TracerProvider 初始化。"""

    def test_creates_provider_and_span(self):
        """setup_telemetry 返回 TracerProvider，可正常创建 span。"""
        from fastapi import FastAPI
        from opentelemetry import trace

        from app.core.config import TelemetryConfig
        from app.core.telemetry import setup_telemetry, shutdown_telemetry

        app = FastAPI()
        config = TelemetryConfig(
            service_name="test-service",
            exporter_endpoint="http://localhost:4317",
            insecure=True,
        )

        provider = setup_telemetry(config, app)
        try:
            tracer = trace.get_tracer("test-tracer")
            with tracer.start_as_current_span("test-span") as span:
                assert span is not None
                ctx = span.get_span_context()
                assert ctx.trace_id != 0
        finally:
            shutdown_telemetry(provider)
