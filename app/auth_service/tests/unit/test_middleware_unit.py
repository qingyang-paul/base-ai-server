
import pytest
from unittest.mock import MagicMock, patch
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import Scope, Receive, Send

from app.auth_service.core.middleware import AuthMiddleware
from jose import JWTError

@pytest.fixture
def mock_app():
    async def app(scope: Scope, receive: Receive, send: Send):
        response = Response("OK")
        await response(scope, receive, send)
    return app

@pytest.mark.asyncio
async def test_auth_middleware_no_header(mock_app):
    middleware = AuthMiddleware(mock_app)
    scope = {"type": "http", "headers": []}
    
    # Mock call_next
    async def call_next(request):
        assert request.state.user_id is None
        return Response("OK")

    await middleware.dispatch(Request(scope), call_next)

@pytest.mark.asyncio
async def test_auth_middleware_invalid_header_format(mock_app):
    middleware = AuthMiddleware(mock_app)
    headers = [(b"authorization", b"Basic 12345")]
    scope = {"type": "http", "headers": headers}

    async def call_next(request):
        assert request.state.user_id is None
        return Response("OK")

    await middleware.dispatch(Request(scope), call_next)

@pytest.mark.asyncio
async def test_auth_middleware_valid_token(mock_app):
    with patch("app.auth_service.core.middleware.decode_token") as mock_decode:
        mock_decode.return_value = {"sub": "user123"}
        
        middleware = AuthMiddleware(mock_app)
        headers = [(b"authorization", b"Bearer validtoken")]
        scope = {"type": "http", "headers": headers}

        async def call_next(request):
            assert request.state.user_id == "user123"
            return Response("OK")

        await middleware.dispatch(Request(scope), call_next)

@pytest.mark.asyncio
async def test_auth_middleware_invalid_token_jwt_error(mock_app):
    with patch("app.auth_service.core.middleware.decode_token") as mock_decode:
        mock_decode.side_effect = JWTError("Invalid token")
        
        middleware = AuthMiddleware(mock_app)
        headers = [(b"authorization", b"Bearer invalidtoken")]
        scope = {"type": "http", "headers": headers}

        async def call_next(request):
            assert request.state.user_id is None
            return Response("OK")

        await middleware.dispatch(Request(scope), call_next)
