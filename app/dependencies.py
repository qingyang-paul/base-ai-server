"""FastAPI 依赖注入工具：从 app.state 获取连接池实例。"""

from collections.abc import AsyncGenerator

import redis.asyncio as aioredis
from fastapi import Request, HTTPException, status


async def get_redis(request: Request) -> aioredis.Redis:
    """获取 Redis 连接池实例。"""
    return request.app.state.redis


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
from redis.asyncio import Redis

from app.auth_service.auth_repo import AuthRepo
from app.auth_service.auth_service import AuthService

from app.chat_service.chat_service import ChatService
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from app.subscription_service.subscription_repo import SubscriptionRepo
from app.subscription_service.subscription_service import SubscriptionService

async def get_db_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    '''从 SQLAlchemy Engine 获取一个 Session'''
    engine = request.app.state.db_engine
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session

async def get_auth_repo(
    session: AsyncSession = Depends(get_db_session),
    redis: Redis = Depends(get_redis)
) -> AuthRepo:
    return AuthRepo(session, redis)

async def get_auth_service(
    repo: AuthRepo = Depends(get_auth_repo)
) -> AuthService:
    return AuthService(repo)

async def get_subscription_repo(
    session: AsyncSession = Depends(get_db_session)
) -> SubscriptionRepo:
    return SubscriptionRepo(session)

async def get_subscription_service(
    repo: SubscriptionRepo = Depends(get_subscription_repo)
) -> SubscriptionService:
    return SubscriptionService(repo)

async def get_chat_service() -> ChatService:
    return ChatService()
