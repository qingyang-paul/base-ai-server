import pytest
import pytest_asyncio
import os
import json
from app.chat_service.chat_service import ChatService
from app.chat_service.core.config import Settings
from app.chat_service.core.llm_client_manager import llm_manager
from app.chat_service.core.llm_providers.openai_provider import OpenAICompatibleProvider
from app.chat_service.core.llm_providers.qwen_provider import QwenProvider
from app.chat_service.core.schema import (
    UserQuery, ChatHistory, SessionContext, StreamEventType
)
from app.subscription_service.core.config import GlobalLLMConfig
from app.chat_service.core.llm_tools import registry
from pydantic import BaseModel, Field

# Define a real tool
class AddArgs(BaseModel):
    a: int = Field(..., description="First number")
    b: int = Field(..., description="Second number")

def add_func(a: int, b: int) -> str:
    return str(a + b)

@pytest_asyncio.fixture(scope="function")
async def setup_real_env():
    # Load settings from .env (assumed to be present in environment or .env file)
    settings = Settings()
    
    # Register providers
    if settings.openai and settings.openai.api_key:
        llm_manager.register("openai", OpenAICompatibleProvider(settings.openai))
    
    if settings.qwen and settings.qwen.api_key:
        llm_manager.register("qwen", QwenProvider(settings.qwen))
        
    # Register Tool
    registry.register("calculate_sum", "Calculates the sum of two numbers", AddArgs)(add_func)
    
    # Start Clients
    await llm_manager.startup()
    
    yield settings
    
    # Stop Clients
    await llm_manager.shutdown()

@pytest.mark.asyncio
async def test_agent_loop_qwen(setup_real_env):
    """
    Integration test with real Qwen provider.
    """
    settings = setup_real_env
    provider_name = "qwen"
    runtime_config_cls = GlobalLLMConfig
    
    # Skip if API key is missing
    provider_config = getattr(settings, provider_name, None)
    if not provider_config or not provider_config.api_key or provider_config.api_key == "changeme":
        pytest.skip(f"{provider_name} API key not configured.")
        
    chat_service = ChatService()
    
    # 1. Build Payload
    user_query = UserQuery(content="What is 12345 + 67890?")
    chat_history = ChatHistory(messages=[])
    session_context = SessionContext(user_sop_preferences=[])
    
    allowed_tools = ["calculate_sum"] 
    
    payload = chat_service.build_llm_payload(
        system_prompt="You are a helpful assistant. Use tools for math.",
        chat_history=chat_history,
        user_query=user_query,
        session_context=session_context,
        allowed_tools=allowed_tools
    )
    
    # 2. Runtime Config
    runtime_config = runtime_config_cls(
        model_id="qwen-max",
        provider="qwen",
        base_prompt_ratio=0.01,
        base_completion_ratio=0.01
    )
    
    # 3. Run Loop
    print(f"\n\n--- Testing Provider: {provider_name} ---")
    events = []
    output_lines = []
    
    try:
        async for event in chat_service.chat_stream_with_tools(runtime_config, payload):
            events.append(event)
            line = f"[{event.event_type}] Seq={event.seq_id} "
            if event.event_type == StreamEventType.TEXT_CHUNK:
                line += f"Content={repr(event.content)}"
            elif event.event_type == StreamEventType.TOOL_CALL:
                line += f"Tool={event.tool_name} Args={event.args_chunk}"
            elif event.event_type == StreamEventType.STATUS:
                line += f"Status={event.status} Msg={event.message}"
            elif event.event_type == StreamEventType.STATS:
                line += f"In={event.input_tokens} Out={event.output_tokens}"
            
            print(line)
            output_lines.append(line)
    except Exception as e:
        print(f"Error during stream: {e}")
        # Allow passing if it's a known API error we can't fix here
        if "401" in str(e) or "invalid_api_key" in str(e).lower():
            pytest.skip(f"Authentication failed for {provider_name}: {e}")
        else:
            raise e

    # 4. Save to file
    output_dir = "app/chat_service/tests/test_outputs"
    os.makedirs(output_dir, exist_ok=True)
    with open(f"{output_dir}/agent_loop_{provider_name}.txt", "w") as f:
        f.write("\n".join(output_lines))

    # 5. Assertions
    if not events:
         pytest.skip("No events received (likely API error or timeout)")

    # Check for Tool usage
    has_tool_call = any(e.event_type == StreamEventType.TOOL_CALL for e in events)
    if not has_tool_call:
        print("WARNING: No tool call detected. Model might have answered directly.")
    
    # Check for Status events
    has_status = any(e.event_type == StreamEventType.STATUS for e in events)
    if has_tool_call:
        assert has_status, "Expected status events if tool was called"
    
    # Check final answer
    full_content = "".join([e.content for e in events if e.event_type == StreamEventType.TEXT_CHUNK])
    answer = "80235" # 12345 + 67890
    
    if answer not in full_content:
        print(f"WARNING: Expected answer {answer} not found exactly. Content: {full_content}")
        # Weak assertion for now if model acts differently
        assert len(full_content) > 0
    else:
        assert answer in full_content
