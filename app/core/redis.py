"""Redis 连接池管理。"""

import redis.asyncio as aioredis
from loguru import logger

from app.core.config import RedisConfig
from app.core.exceptions import RedisConnectionError


async def init_redis_pool(config: RedisConfig) -> aioredis.Redis:
    """初始化 Redis 连接池并验证连通性。"""
    url = f"redis://{config.host}:{config.port}/{config.db}"
    pool = aioredis.from_url(
        url,
        password=config.password,
        max_connections=config.max_connections,
        decode_responses=True,
    )
    try:
        await pool.ping()
        logger.info("Redis connection pool initialized", host=config.host, port=config.port)
    except Exception as exc:
        await pool.aclose()
        raise RedisConnectionError(detail=str(exc)) from exc
    return pool


async def close_redis_pool(pool: aioredis.Redis) -> None:
    """关闭 Redis 连接池。"""
    await pool.aclose()
    logger.info("Redis connection pool closed")


async def check_redis_health(pool: aioredis.Redis) -> bool:
    """检查 Redis 连接是否可用。"""
    try:
        return await pool.ping()
    except Exception:
        return False