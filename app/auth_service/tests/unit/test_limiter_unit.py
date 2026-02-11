
import pytest
from unittest.mock import MagicMock
from starlette.requests import Request
from app.auth_service.core.limiter import rate_limit_key_builder

@pytest.mark.asyncio
async def test_key_builder_user_id():
    scope = {"type": "http", "client": ("127.0.0.1", 8000), "headers": []}
    request = Request(scope)
    request.state.user_id = "user123"
    
    key = await rate_limit_key_builder(request)
    assert key == "user:user123"

@pytest.mark.asyncio
async def test_key_builder_x_forwarded_for():
    headers = [(b"x-forwarded-for", b"10.0.0.1, 192.168.1.1")]
    scope = {"type": "http", "client": ("127.0.0.1", 8000), "headers": headers}
    request = Request(scope)
    request.state.user_id = None
    
    key = await rate_limit_key_builder(request)
    assert key == "ip:10.0.0.1"

@pytest.mark.asyncio
async def test_key_builder_client_host():
    scope = {"type": "http", "client": ("192.168.1.5", 8000), "headers": []}
    request = Request(scope)
    request.state.user_id = None
    
    key = await rate_limit_key_builder(request)
    assert key == "ip:192.168.1.5"
