import json
import os

import pytest

os.environ.setdefault("LOG_JSON_FORMAT", "true")
os.environ.setdefault("OTEL_SERVICE_NAME", "test-service")
os.environ.setdefault("OTEL_EXPORTER_ENDPOINT", "http://localhost:4317")
os.environ.setdefault("OTEL_INSECURE", "true")
os.environ.setdefault("WORK_ENVIRONMENT", "testing")


class TestJsonLogOutput:
    """验证 JSON 格式日志输出。"""

    def test_json_format_parseable(self, capsys):
        """setup_logging 正常执行，JSON 格式输出可被解析。"""
        from loguru import logger as loguru_logger

        from app.core.config import LoggerConfig
        from app.core.logger import setup_logging

        config = LoggerConfig(json_format=True)
        setup_logging(config)

        loguru_logger.info("test log message")

        captured = capsys.readouterr()
        log_line = captured.out.strip().split("\n")[-1]
        log_entry = json.loads(log_line)

        assert log_entry["level"] == "INFO"
        assert log_entry["message"] == "test log message"
        assert "trace_id" in log_entry
        assert "timestamp" in log_entry
        assert "module" in log_entry

    def test_text_format_output(self, capsys):
        """非 JSON 模式下，输出可读文本格式。"""
        from loguru import logger as loguru_logger

        from app.core.config import LoggerConfig
        from app.core.logger import setup_logging

        config = LoggerConfig(json_format=False)
        setup_logging(config)

        loguru_logger.info("text format test")

        captured = capsys.readouterr()
        assert "text format test" in captured.out


class TestTraceIdInjection:
    """验证 OTel trace_id 注入日志。"""

    def test_trace_id_zero_without_span(self, capsys):
        """无活跃 span 时，trace_id 为全零。"""
        from loguru import logger as loguru_logger

        from app.core.config import LoggerConfig
        from app.core.logger import setup_logging

        config = LoggerConfig(json_format=True)
        setup_logging(config)

        loguru_logger.info("trace id check")

        captured = capsys.readouterr()
        log_line = captured.out.strip().split("\n")[-1]
        log_entry = json.loads(log_line)
        assert log_entry["trace_id"] == "0" * 32

    def test_trace_id_nonzero_inside_span(self, capsys):
        """在活跃 span 内，日志中的 trace_id 非全零。"""
        from fastapi import FastAPI
        from loguru import logger as loguru_logger
        from opentelemetry import trace

        from app.core.config import LoggerConfig, TelemetryConfig
        from app.core.logger import setup_logging
        from app.core.telemetry import setup_telemetry, shutdown_telemetry

        config = LoggerConfig(json_format=True)
        setup_logging(config)

        app = FastAPI()
        tel_config = TelemetryConfig(
            service_name="test-service",
            exporter_endpoint="http://localhost:4317",
            insecure=True,
        )
        provider = setup_telemetry(tel_config, app)

        try:
            tracer = trace.get_tracer("test-tracer")
            with tracer.start_as_current_span("test-span"):
                loguru_logger.info("inside span")

            captured = capsys.readouterr()
            log_line = captured.out.strip().split("\n")[-1]
            log_entry = json.loads(log_line)
            assert log_entry["trace_id"] != "0" * 32
            assert len(log_entry["trace_id"]) == 32
        finally:
            shutdown_telemetry(provider)
