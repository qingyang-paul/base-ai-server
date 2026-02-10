"""将自定义异常映射到 FastAPI HTTP 响应。

数据库等基础设施宕机时，统一返回模糊信息，不泄露内部细节。
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from loguru import logger

from app.core.exceptions import DatabaseConnectionError


def register_exception_handlers(app: FastAPI) -> None:
    """注册全局异常处理器。"""

    @app.exception_handler(DatabaseConnectionError)
    async def database_connection_error_handler(
        request: Request,
        exc: DatabaseConnectionError,
    ) -> JSONResponse:
        logger.error(
            "Database connection error: {service} - {detail}",
            service=exc.service,
            detail=exc.detail,
        )
        return JSONResponse(
            status_code=503,
            content={"detail": "Service temporarily unavailable"},
        )
