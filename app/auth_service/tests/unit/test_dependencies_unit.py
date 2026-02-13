import pytest
from fastapi import Request
from app.auth_service.core.dependencies import get_client_info, ClientInfo

@pytest.mark.asyncio
async def test_get_client_info_with_x_forwarded_for():
    scope = {
        "type": "http",
        "headers": [
            (b"x-forwarded-for", b"10.0.0.1, 10.0.0.2"),
            (b"user-agent", b"TestAgent/1.0"),
        ],
    }
    request = Request(scope)
    
    info = await get_client_info(request)
    
    assert info.ip_address == "10.0.0.1"
    assert info.device_name == "TestAgent/1.0"

@pytest.mark.asyncio
async def test_get_client_info_without_x_forwarded_for():
    scope = {
        "type": "http",
        "headers": [
            (b"user-agent", b"TestAgent/1.0"),
        ],
        "client": ("192.168.1.1", 12345),
    }
    request = Request(scope)
    
    info = await get_client_info(request)
    
    assert info.ip_address == "192.168.1.1"
    assert info.device_name == "TestAgent/1.0"

@pytest.mark.asyncio
async def test_get_client_info_fallback():
    scope = {
        "type": "http",
        "headers": [],
        "client": None,
    }
    request = Request(scope)
    
    info = await get_client_info(request)
    
    assert info.ip_address == "unknown"
    assert info.device_name == "unknown"
