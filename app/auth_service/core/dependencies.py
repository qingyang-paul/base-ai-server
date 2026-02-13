from fastapi import Request
from pydantic import BaseModel

class ClientInfo(BaseModel):
    ip_address: str
    device_name: str

async def get_client_info(request: Request) -> ClientInfo:
    """
    Extracts client IP and device name from request headers.
    """
    # 1. IP extraction
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        ip_address = forwarded.split(',')[0].strip()
    elif request.client and request.client.host:
        ip_address = request.client.host
    else:
        ip_address = "unknown"
        
    # 2. Device extraction
    user_agent = request.headers.get("User-Agent", "unknown")
    # Simple extraction, can be enhanced with user-agent-parser later if needed
    device_name = user_agent[:100] # Truncate to reasonable length
    
    return ClientInfo(ip_address=ip_address, device_name=device_name)