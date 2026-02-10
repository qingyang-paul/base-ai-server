"""FastAPI 依赖注入工具：从 app.state 获取连接池实例。"""

from collections.abc import AsyncGenerator

import asyncpg
import redis.asyncio as aioredis
from fastapi import Request


async def get_redis(request: Request) -> aioredis.Redis:
    """获取 Redis 连接池实例。"""
    return request.app.state.redis


async def get_postgres(request: Request) -> AsyncGenerator[asyncpg.Connection, None]:
    """从 Postgres 连接池获取连接，请求结束后自动释放。"""
    pool: asyncpg.Pool = request.app.state.postgres
    async with pool.acquire() as connection:
        yield connection
