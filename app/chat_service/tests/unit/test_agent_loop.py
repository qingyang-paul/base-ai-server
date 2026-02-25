import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from app.chat_service.chat_service import ChatService
from app.chat_service.core.schema import (
    LLMPayload, StreamEventType, MessageChunkEvent, 
    ToolCallChunkEvent, StatusEvent, RoleType, LLMMessage, ToolCall, ToolCallFunction, RunFinishEvent
)
from app.subscription_service.core.config import GlobalLLMConfig
from app.chat_service.core.llm_tools import registry
from pydantic import BaseModel

# Mock Config
class MockRuntimeConfig(BaseModel):
    provider: str = "mock_provider"
    model_id: str = "mock_model"

# Mock Tool
class MockToolArgs(BaseModel):
    arg1: str

def mock_tool_func(arg1: str):
    return f"Executed with {arg1}"

@pytest.fixture
def chat_service():
    service = ChatService()
    # Register a mock tool
    registry.register("mock_tool", "A mock tool", MockToolArgs)(mock_tool_func)
    service.tools = registry.tools # Refresh tools
    return service

@pytest.mark.asyncio
async def test_agent_loop_no_tools(chat_service):
    """Test simple conversation without tool calls."""
    mock_provider = AsyncMock()
    
    # Provider returns text chunks
    async def mock_stream_reply(config, payload):
        yield MessageChunkEvent(seq_id=1, content="Hello")
        yield MessageChunkEvent(seq_id=2, content=" World")
    
    mock_provider.stream_reply = mock_stream_reply
    
    with patch("app.chat_service.chat_service.llm_manager") as mock_manager:
        mock_manager.get_provider.return_value = mock_provider
        
        payload = LLMPayload(messages=[LLMMessage(role=RoleType.USER, content="Hi")])
        config = MockRuntimeConfig(provider="mock_provider")
        
        events = []
        async for event in chat_service.chat_stream_with_tools(config, payload):
            events.append(event)
            
        assert len(events) == 3
        assert events[0].content == "Hello"
        assert events[1].content == " World"
        assert isinstance(events[-1], RunFinishEvent)

@pytest.mark.asyncio
async def test_agent_loop_single_tool_call(chat_service):
    """Test single tool execution flow."""
    mock_provider = AsyncMock()
    
    # Mock provider behavior: 
    # Round 1: Yield Tool Call
    # Round 2: Yield Final Response
    async def mock_stream_reply_round_1(config, payload):
        # Determine if this is round 1 (no tool results yet) or round 2
        last_msg = payload.messages[-1]
        if last_msg.role == RoleType.USER: # Round 1
            yield ToolCallChunkEvent(seq_id=1, tool_name="mock_tool", args_chunk='{"arg1": "test"}', index=0)
        else: # Round 2 (Tool result is in history)
            yield MessageChunkEvent(seq_id=1, content="Tool executed.")

    mock_provider.stream_reply = mock_stream_reply_round_1
    
    with patch("app.chat_service.chat_service.llm_manager") as mock_manager:
        mock_manager.get_provider.return_value = mock_provider
        
        payload = LLMPayload(messages=[LLMMessage(role=RoleType.USER, content="Run tool")])
        config = MockRuntimeConfig(provider="mock_provider")
        
        events = []
        async for event in chat_service.chat_stream_with_tools(config, payload):
            events.append(event)
        
        # Verify Event Sequence:
        # 1. ToolCallChunkEvent (Round 1)
        # 2. StatusEvent (Running)
        # 3. StatusEvent (Success)
        # 4. StatusEvent (Thinking - Round 2)
        # 5. MessageChunkEvent (Round 2)
        
        # Note: Implementation yields StatusEvent(Thinking) only if loop_count > 1
        
        types = [type(e) for e in events]
        assert ToolCallChunkEvent in types
        assert StatusEvent in types
        assert MessageChunkEvent in types
        
        # Check specific StatusEvents
        status_events = [e for e in events if isinstance(e, StatusEvent)]
        # Check for tool execution status events (running and success)
        assert any(e.status == "running" and e.tool_name == "mock_tool" for e in status_events)
        assert any(e.status == "success" and e.tool_name == "mock_tool" for e in status_events)
        # Check for thinking status event (only in loop > 1)
        assert any(e.message == "正在思考总结..." for e in status_events)

@pytest.mark.asyncio
async def test_agent_loop_max_loops(chat_service):
    """Test max loops enforcement."""
    mock_provider = AsyncMock()
    
    # Always return tool call
    async def mock_stream_reply(config, payload):
         yield ToolCallChunkEvent(seq_id=1, tool_name="mock_tool", args_chunk='{"arg1": "loop"}', index=0)
    
    mock_provider.stream_reply = mock_stream_reply
    
    with patch("app.chat_service.chat_service.llm_manager") as mock_manager, \
         patch("app.chat_service.chat_service.settings") as mock_settings:
        mock_manager.get_provider.return_value = mock_provider
        mock_settings.agent_max_loops = 2
        
        payload = LLMPayload(messages=[LLMMessage(role=RoleType.USER, content="Run forever")])
        config = MockRuntimeConfig(provider="mock_provider")
        
        events = []
        async for event in chat_service.chat_stream_with_tools(config, payload):
            events.append(event)
            
        # Should end with forced stop message
        # Should end with forced stop message and then RunFinishEvent
        assert isinstance(events[-2], MessageChunkEvent)
        assert "操作超限" in events[-2].content
        assert isinstance(events[-1], RunFinishEvent)
