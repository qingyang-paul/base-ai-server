"""Postgres 连接池管理。"""

from collections.abc import AsyncGenerator

import asyncpg
from loguru import logger

from app.core.config import PostgresConfig
from app.core.exceptions import PostgresConnectionError


async def init_postgres_pool(config: PostgresConfig) -> asyncpg.Pool:
    """初始化 Postgres 连接池。"""
    dsn = f"postgresql://{config.user}:{config.password}@{config.host}:{config.port}/{config.database}"
    try:
        pool = await asyncpg.create_pool(
            dsn=dsn,
            min_size=config.min_pool_size,
            max_size=config.max_pool_size,
        )
        logger.info("Postgres connection pool initialized", host=config.host, port=config.port)
    except Exception as exc:
        raise PostgresConnectionError(detail=str(exc)) from exc
    return pool


async def close_postgres_pool(pool: asyncpg.Pool) -> None:
    """关闭 Postgres 连接池。"""
    await pool.close()
    logger.info("Postgres connection pool closed")


async def get_postgres_connection(pool: asyncpg.Pool) -> AsyncGenerator[asyncpg.Connection, None]:
    """从连接池获取一个连接，使用完毕后自动释放。"""
    async with pool.acquire() as connection:
        yield connection


async def check_postgres_health(pool: asyncpg.Pool) -> bool:
    """检查 Postgres 连接是否可用。"""
    try:
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        return True
    except Exception:
        return False