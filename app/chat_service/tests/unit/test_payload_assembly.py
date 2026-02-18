
import pytest
from uuid import uuid4
from typing import List
from pydantic import ValidationError
from app.chat_service.core.schema import (
    RoleType, ToolCall, ToolCallFunction, LLMMessage, ChatHistory, 
    LLMPayload, UserQuery, SOPPreference, SessionContext
)
from app.chat_service.chat_service import ChatService
from app.chat_service.core.llm_tools import FuncName, registry
from pydantic import BaseModel

# --- Schema Unit Tests ---

def test_llm_message_model():
    """Test LLMMessage model validation."""
    # Valid user message
    msg = LLMMessage(role=RoleType.USER, content="Hello")
    assert msg.role == "user"
    assert msg.content == "Hello"

    # Valid assistant message with tool calls
    tool_call = ToolCall(
        id="call_123",
        function=ToolCallFunction(name="get_weather", arguments='{"location": "Beijing"}')
    )
    msg = LLMMessage(role=RoleType.ASSISTANT, tool_calls=[tool_call])
    assert msg.role == "assistant"
    assert msg.tool_calls[0].id == "call_123"

def test_chat_history_model():
    """Test ChatHistory model."""
    msg1 = LLMMessage(role=RoleType.USER, content="Hi")
    msg2 = LLMMessage(role=RoleType.ASSISTANT, content="Hello")
    history = ChatHistory(messages=[msg1, msg2])
    assert len(history.messages) == 2

# --- ChatService payload assembly tests ---

@pytest.fixture
def chat_service():
    return ChatService()

class MockArgs(BaseModel):
    arg1: str

def mock_func(arg1: str):
    return "result"

@pytest.fixture
def registered_tool():
    # Register a mock tool directly into registry for testing
    # Note: registry is global, so we should clean up or use unique names
    name = "mock_tool_test"
    registry.register(name, "A mock tool", MockArgs)(mock_func)
    yield name
    # Cleanup if registry had unregister method, but for now it's fine as it's just a dict
    if name in registry.tools:
        del registry.tools[name]

def test_build_llm_payload_basic(chat_service):
    """Test basic payload assembly without SOP or tools."""
    system_prompt = "You are a helper."
    history = ChatHistory(messages=[
        LLMMessage(role=RoleType.USER, content="Hi"),
        LLMMessage(role=RoleType.ASSISTANT, content="Hello there")
    ])
    user_query = UserQuery(content="How are you?")
    session_context = SessionContext(user_sop_preferences=[])
    allowed_tools = []

    payload = chat_service.build_llm_payload(
        system_prompt, history, user_query, session_context, allowed_tools
    )

    assert isinstance(payload, LLMPayload)
    assert len(payload.messages) == 4 # System + 2 History + 1 UserQuery
    assert payload.messages[0].role == RoleType.SYSTEM
    assert payload.messages[0].content == system_prompt
    assert payload.messages[-1].role == RoleType.USER
    assert payload.messages[-1].content == "How are you?"
    assert payload.tools is None
    assert payload.tool_choice is None

def test_build_llm_payload_with_sop(chat_service):
    """Test payload assembly with SOP preferences."""
    system_prompt = "Base prompt."
    sop = SOPPreference(
        id=uuid4(), user_id=uuid4(), session_ids=[], 
        subject="Tone", content="Be polite", keywords=[]
    )
    session_context = SessionContext(user_sop_preferences=[sop])
    
    payload = chat_service.build_llm_payload(
        "Base prompt.", 
        ChatHistory(messages=[]), 
        UserQuery(content="Hi"), 
        session_context, 
        []
    )
    
    system_msg = payload.messages[0]
    assert "Base prompt." in system_msg.content
    assert "User SOP Preferences:" in system_msg.content
    assert "- [Tone]: Be polite" in system_msg.content

def test_build_llm_payload_with_tools(chat_service, registered_tool):
    """Test payload assembly with allowed tools."""
    # We need to use a FuncName that maps to our registered tool
    # Since FuncName is Enum, we can't easily add to it at runtime without hacking.
    # But allowed_tools is List[FuncName], type hint says FuncName but logic uses .value
    # Let's mock the enum or just pass string if type checking allows (Python does at runtime)
    # The method expects list members to have .value or be the value.
    
    # Adding a temporary member to the Enum is hard. 
    # Let's assume the method handles strings purely or we Mock the enum passed in.
    # The implementation: `name_str = tool_name.value if hasattr(tool_name, 'value') else tool_name`
    # So passing the string directly works.
    
    payload = chat_service.build_llm_payload(
        "Prompt", 
        ChatHistory(messages=[]), 
        UserQuery(content="Use tool"), 
        SessionContext(user_sop_preferences=[]), 
        allowed_tools=[registered_tool] # passing string "mock_tool_test"
    )
    
    assert payload.tools is not None
    assert len(payload.tools) == 1
    assert payload.tools[0]["function"]["name"] == registered_tool
    assert payload.tool_choice == "auto"

