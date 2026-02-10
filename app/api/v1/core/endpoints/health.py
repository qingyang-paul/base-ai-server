"""Health check endpoint — 检查 Redis 和 Postgres 的连接状况。"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.core.postgres import check_postgres_health
from app.core.redis import check_redis_health

router = APIRouter()


@router.get("/health")
async def health_check(request: Request) -> JSONResponse:
    """检查 Redis 和 Postgres 是否正常连接。"""
    redis_ok = await check_redis_health(request.app.state.redis)
    postgres_ok = await check_postgres_health(request.app.state.postgres)

    status = "healthy" if (redis_ok and postgres_ok) else "unhealthy"
    status_code = 200 if status == "healthy" else 503

    return JSONResponse(
        status_code=status_code,
        content={
            "status": status,
            "redis": "up" if redis_ok else "down",
            "postgres": "up" if postgres_ok else "down",
        },
    )
