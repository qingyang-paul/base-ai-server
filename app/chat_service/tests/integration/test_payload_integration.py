
import pytest
from typing import List, Dict, Any
from uuid import uuid4
from pydantic import BaseModel, Field

from app.chat_service.core.schema import (
    RoleType, ToolCall, ToolCallFunction, LLMMessage, ChatHistory, 
    LLMPayload, UserQuery, SOPPreference, SessionContext
)
from app.chat_service.chat_service import ChatService
from app.chat_service.core.llm_tools import FuncName, registry

# --- Mock Data ---

class WeatherArgs(BaseModel):
    location: str = Field(..., description="City name")
    unit: str = Field("celsius", description="Temperature unit")

def get_weather(location: str, unit: str = "celsius"):
    return "25C"

class OrderArgs(BaseModel):
    user_id: str = Field(..., description="User ID")

def get_orders(user_id: str):
    return "Order #123"

@pytest.fixture
def chat_service_with_tools():
    # Register mock tools
    # Using real FuncName values for realism if possible, or new ones
    
    # We'll use "get_weather" which exists in FuncName enum (assumption from previous steps)
    # And maybe "get_user_orders"
    
    registry.register("get_weather", "Get weather info", WeatherArgs)(get_weather)
    registry.register("get_user_orders", "Get user orders", OrderArgs)(get_orders)
    
    service = ChatService()
    yield service
    
    # Cleanup
    if "get_weather" in registry.tools:
        del registry.tools["get_weather"]
    if "get_user_orders" in registry.tools:
        del registry.tools["get_user_orders"]

@pytest.mark.asyncio
async def test_complex_payload_assembly(chat_service_with_tools):
    """
    Integration test for payload assembly with:
    1. System prompt
    2. SOP preferences
    3. Multi-turn chat history
    4. Multiple allowed tools
    """
    # 1. Setup Context
    sop1 = SOPPreference(
        id=uuid4(), user_id=uuid4(), session_ids=[], 
        subject="Tone", content="Be professional", keywords=[]
    )
    sop2 = SOPPreference(
        id=uuid4(), user_id=uuid4(), session_ids=[], 
        subject="Language", content="Use English", keywords=[]
    )
    context = SessionContext(user_sop_preferences=[sop1, sop2])
    
    # 2. Setup History
    history = ChatHistory(messages=[
        LLMMessage(role=RoleType.USER, content="Hello"),
        LLMMessage(role=RoleType.ASSISTANT, content="Hi there"),
        LLMMessage(role=RoleType.USER, content="What's the weather?"),
        # Start of a tool call turn
        LLMMessage(role=RoleType.ASSISTANT, tool_calls=[
            ToolCall(id="call_1", function=ToolCallFunction(name="get_weather", arguments='{"location": "Tokyo"}'))
        ]),
        LLMMessage(role=RoleType.TOOL, tool_call_id="call_1", name="get_weather", content="Sunny, 20C")
    ])
    
    # 3. New Query
    query = UserQuery(content="And my orders?")
    
    # 4. Allowed Tools
    # We use strings here to simulate passing FuncName members (or their values)
    allowed_tools = ["get_weather", "get_user_orders"]
    
    # Act
    payload = chat_service_with_tools.build_llm_payload(
        system_prompt="You are a helper.",
        chat_history=history,
        user_query=query,
        session_context=context,
        allowed_tools=allowed_tools
    )
    
    # Assert
    
    # System Prompt check
    system_msg = payload.messages[0]
    assert system_msg.role == RoleType.SYSTEM
    assert "You are a helper." in system_msg.content
    assert "- [Tone]: Be professional" in system_msg.content
    assert "- [Language]: Use English" in system_msg.content
    
    # Tool Generation Check
    assert payload.tools is not None
    assert len(payload.tools) == 2
    
    # Verify schema generation
    weather_tool_schema = next(t for t in payload.tools if t["function"]["name"] == "get_weather")
    assert weather_tool_schema["function"]["description"] == "Get weather info"
    props = weather_tool_schema["function"]["parameters"]["properties"]
    assert "location" in props
    assert "unit" in props
    
    # Message Sequence Check
    # 1 System + 5 History + 1 User = 7 messages
    assert len(payload.messages) == 7
    assert payload.messages[-1].content == "And my orders?"
    assert payload.messages[-2].role == RoleType.TOOL
    
    print("Payload validation successful!")
