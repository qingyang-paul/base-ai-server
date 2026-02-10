import json
import logging
import sys
from datetime import datetime, timezone

from loguru import logger
from opentelemetry import trace

from app.core.config import LoggerConfig


def _otel_trace_patcher(record: dict) -> None:
    """从当前 OTel span context 中抓取 trace_id，注入到 loguru record extra。"""
    span = trace.get_current_span()
    ctx = span.get_span_context()
    if ctx and ctx.trace_id != 0:
        record["extra"]["trace_id"] = format(ctx.trace_id, "032x")
    else:
        record["extra"]["trace_id"] = "0" * 32


class InterceptHandler(logging.Handler):
    """拦截标准库 logging 的信息，转发给 loguru。"""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame, depth = logging.currentframe(), 0
        while frame and (depth == 0 or frame.f_code.co_filename == logging.__file__):
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def _json_sink(message) -> None:
    """自定义 sink：将 loguru record 组装成 JSON 格式输出到 stdout。"""
    record = message.record
    log_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "level": record["level"].name,
        "message": record["message"],
        "trace_id": record["extra"].get("trace_id", "0" * 32),
        "module": record["module"],
        "function": record["function"],
        "line": record["line"],
    }
    sys.stdout.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def setup_logging(config: LoggerConfig) -> None:
    """Logger 启动入口。"""
    # 移除 loguru 默认 handler
    logger.remove()

    # 配置 patcher（注入 trace_id）
    logger.configure(patcher=_otel_trace_patcher)

    # 根据配置选择输出格式
    if config.json_format:
        logger.add(_json_sink, level="DEBUG")
    else:
        logger.add(
            sys.stdout,
            level="DEBUG",
            format=(
                "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
                "<level>{level: <8}</level> | "
                "<cyan>{extra[trace_id]}</cyan> | "
                "<cyan>{module}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
                "<level>{message}</level>"
            ),
        )

    # 拦截 uvicorn / httpx 等标准库 logger
    for logger_name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        logging_logger = logging.getLogger(logger_name)
        logging_logger.handlers = [InterceptHandler()]
        logging_logger.propagate = False