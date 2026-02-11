
from fastapi import Request
from fastapi_limiter import FastAPILimiter
import redis.asyncio as aioredis


async def rate_limit_key_builder(request: Request):
    """
    Constructs a rate limit key based on user identity or IP address.
    """
    # 1. Try to get user_id from request.state (set by AuthMiddleware)
    user_id = getattr(request.state, "user_id", None)
    if user_id:
        return f"user:{user_id}"
    
    # 2. Fallback to IP address
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return f"ip:{forwarded.split(',')[0].strip()}"
    
    if request.client and request.client.host:
        return f"ip:{request.client.host}"
    
    return "ip:unknown"


async def init_limiter(redis: aioredis.Redis):
    """
    Initializes the FastAPILimiter with the Redis connection.
    """
    await FastAPILimiter.init(
        redis,
        identifier=rate_limit_key_builder
    )
