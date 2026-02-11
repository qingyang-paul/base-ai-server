
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from jose import JWTError
from loguru import logger

from app.auth_service.core.security import decode_token


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request.state.user_id = None
        
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
            try:
                payload = decode_token(token)
                user_id = payload.get("sub")
                if user_id:
                    request.state.user_id = user_id
            except JWTError as e:
                logger.warning(f"Invalid token: {e}")
            except Exception as e:
                logger.error(f"Error decoding token: {e}")

        response = await call_next(request)
        return response
