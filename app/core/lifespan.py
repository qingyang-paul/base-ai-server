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

    # ================================
    # 1. 动态注册你需要的模型客户端 (Level 3)
    # ================================
    try:
        from app.chat_service.core.config import settings as llm_settings
        from app.chat_service.core.llm_client_manager import llm_manager
        from app.chat_service.core.llm_providers.openai_provider import OpenAICompatibleProvider
        from app.chat_service.core.llm_providers.gemini_provider import GeminiProvider

        # 注册原版 OpenAI
        openai_config = getattr(llm_settings, 'openai', None)
        if openai_config:
            llm_manager.register("openai", OpenAICompatibleProvider(openai_config))
        
        # 注册 Qwen (使用 OpenAI 兼容协议)
        qwen_config = getattr(llm_settings, 'qwen', None)
        if qwen_config:
            llm_manager.register("qwen", OpenAICompatibleProvider(qwen_config))
        
        # 注册 Gemini
        gemini_config = getattr(llm_settings, 'gemini', None)
        if gemini_config:
            llm_manager.register("gemini", GeminiProvider(gemini_config))

        # ================================
        # 2. 统一初始化
        # ================================
        logger.info("🚀 正在初始化所有 LLM 客户端...")
        await llm_manager.startup()
    except Exception as e:
        logger.error(f"Failed to initialize LLM clients: {e}")

    logger.info("Application started")


    yield

    # 关闭连接池
    logger.info("Application stopping")
    await close_redis_pool(redis_pool)
    await close_postgres_pool(postgres_pool)
    
    # ================================
    # 3. 统一销毁
    # ================================
    try:
        from app.chat_service.core.llm_client_manager import llm_manager
        logger.info("📉 正在销毁所有 LLM 客户端...")
        await llm_manager.shutdown()
    except Exception as e:
        logger.error(f"Failed to shutdown LLM clients: {e}")

    shutdown_telemetry(provider)
    await broker.shutdown()