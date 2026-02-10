from contextlib import asynccontextmanager

from fastapi import FastAPI
from loguru import logger

from app.core.config import Settings
from app.core.logger import setup_logging
from app.core.telemetry import setup_telemetry, shutdown_telemetry


@asynccontextmanager
async def lifespan(app: FastAPI):
    """管理 logger 和 telemetry 的生命周期。"""
    settings = Settings()

    # 启动
    setup_logging(settings.logger)
    provider = setup_telemetry(settings.telemetry, app)
    logger.info("Application started")

    yield

    # 关闭
    logger.info("Application stopping")
    shutdown_telemetry(provider)