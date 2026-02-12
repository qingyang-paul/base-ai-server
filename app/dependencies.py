"""FastAPI 依赖注入工具：从 app.state 获取连接池实例。"""

from collections.abc import AsyncGenerator

import asyncpg
import redis.asyncio as aioredis
from fastapi import Request, HTTPException, status


async def get_redis(request: Request) -> aioredis.Redis:
    """获取 Redis 连接池实例。"""
    return request.app.state.redis


async def get_postgres(request: Request) -> AsyncGenerator[asyncpg.Connection, None]:
    """从 Postgres 连接池获取连接，请求结束后自动释放。"""
    pool: asyncpg.Pool = request.app.state.postgres
    async with pool.acquire() as connection:
        yield connection


async def get_current_user_id(request: Request) -> str:
    """从 request.state 获取当前用户 ID，如果不存在则抛出 401。"""
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user_id

from fastapi import Depends
from asyncpg import Connection
from redis.asyncio import Redis

from app.auth_service.auth_repo import AuthRepo
from app.auth_service.auth_service import AuthService

async def get_auth_repo(
    connection: Connection = Depends(get_postgres),
    redis: Redis = Depends(get_redis)
) -> AuthRepo:
    return AuthRepo(connection, redis)

async def get_auth_service(
    repo: AuthRepo = Depends(get_auth_repo)
) -> AuthService:
    return AuthService(repo)

