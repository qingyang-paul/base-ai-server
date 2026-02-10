import json
import os
import sys

import pytest

os.environ.setdefault("LOG_JSON_FORMAT", "true")
os.environ.setdefault("OTEL_SERVICE_NAME", "test-service")
os.environ.setdefault("OTEL_EXPORTER_ENDPOINT", "http://localhost:4317")
os.environ.setdefault("OTEL_INSECURE", "true")
os.environ.setdefault("WORK_ENVIRONMENT", "testing")


class TestAppLifespan:
    """验证 FastAPI 应用 lifespan 启动流程。"""

    @pytest.mark.asyncio
    async def test_lifespan_initializes_logger_and_telemetry(self):
        """手动触发 lifespan，验证日志输出和 HTTP 请求正常。"""
        import io

        import httpx

        from app.core.lifespan import lifespan
        from app.main import app

        captured_io = io.StringIO()
        original_stdout = sys.stdout
        sys.stdout = captured_io

        try:
            async with lifespan(app):
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                    response = await client.get("/openapi.json")
                    assert response.status_code == 200
        finally:
            sys.stdout = original_stdout

        log_output = captured_io.getvalue()

        assert "Application started" in log_output

        for line in log_output.strip().split("\n"):
            if "Application started" in line:
                log_entry = json.loads(line)
                assert "trace_id" in log_entry
                assert log_entry["level"] == "INFO"
                break
