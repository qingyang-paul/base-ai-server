from contextlib import asynccontextmanager

from fastapi import FastAPI
from loguru import logger

from app.core.config import Settings
from app.core.logger import setup_logging
from app.core.postgres import close_postgres_pool, init_postgres_pool
from app.core.redis import close_redis_pool, init_redis_pool
from app.core.telemetry import setup_telemetry, shutdown_telemetry
from app.auth_service.core.limiter import init_limiter
from app.taskiq import broker



@asynccontextmanager
async def lifespan(app: FastAPI):
    """管理 logger、telemetry、Redis、Postgres 的生命周期。"""
    settings = Settings()

    # 启动 logger & telemetry
    setup_logging(settings.logger)
    provider = setup_telemetry(settings.telemetry, app)

    # 启动连接池
    redis_pool = await init_redis_pool(settings.redis)
    postgres_pool = await init_postgres_pool(settings.postgres)

    # 挂载到 app.state 供 dependency 使用
    app.state.redis = redis_pool
    app.state.postgres = postgres_pool

    # 初始化限流器
    await init_limiter(redis_pool)

    # 启动 Taskiq Broker
    if not broker.is_worker_process:
        await broker.startup()

    logger.info("Application started")


    yield

    # 关闭连接池
    logger.info("Application stopping")
    await close_redis_pool(redis_pool)
    await close_postgres_pool(postgres_pool)
    shutdown_telemetry(provider)
    await broker.shutdown()