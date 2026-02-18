import asyncio
import os
import sys
import json
from dotenv import load_dotenv
from pydantic import BaseModel, Field

# Ensure project root is in path
sys.path.insert(0, os.getcwd())

# Load environment variables
load_dotenv()

from app.chat_service.core.config import settings
from app.chat_service.core.llm_client_manager import llm_manager
from app.chat_service.core.llm_providers.openai_provider import OpenAICompatibleProvider
from app.chat_service.core.llm_providers.gemini_provider import GeminiProvider
from app.chat_service.chat_service import ChatService
from app.chat_service.core.llm_tools import registry
from app.chat_service.core.schema import (
    UserQuery, ChatHistory, SessionContext, QwenRuntimeConfig, GeminiRuntimeConfig,
    StreamEventType, RoleType
)

# --- Define Local Tool ---
class SumArgs(BaseModel):
    a: int = Field(..., description="The first number")
    b: int = Field(..., description="The second number")

tool_name = "calculate_sum"

@registry.register(tool_name, "Calculate the sum of two integers.", SumArgs)
def calculate_sum(a: int, b: int) -> int:
    return a + b

async def test_tool_use():
    print("🚀 Starting Tool Use Integration Test via ChatService Logic")
    
    # 1. Setup Manager
    print("--- Setting up LLM Manager ---")
    if hasattr(settings, 'gemini') and settings.gemini:
        llm_manager.register("gemini", GeminiProvider(settings.gemini))
    
    if hasattr(settings, 'qwen') and settings.qwen:
        llm_manager.register("qwen", OpenAICompatibleProvider(settings.qwen))
        
    await llm_manager.startup()
    service = ChatService()

    # 2. Prepare Context (Common for both)
    system_prompt = "You are a helpful assistant. Use tools when necessary."
    chat_history = ChatHistory(messages=[])
    user_query = UserQuery(content="What is 123 + 456?")
    session_context = SessionContext(user_sop_preferences=[])
    
    # 3. Build Payload using ChatService logic
    # We pass the tool_name as string since ChatService supports it
    payload = service.build_llm_payload(
        system_prompt=system_prompt,
        chat_history=chat_history,
        user_query=user_query,
        session_context=session_context,
        allowed_tools=[tool_name]
    )
    
    print("\n✅ Payload Built successfully.")
    print(f"   Tools in payload: {[t['function']['name'] for t in payload.tools] if payload.tools else 'None'}")

    # ==========================
    # Test Qwen
    # ==========================
    print("\n\n🧪 Testing Qwen Tool Use...")
    if "qwen" in llm_manager.providers:
        qwen_model = settings.qwen.model if hasattr(settings, 'qwen') and settings.qwen.model else "qwen-max"
        config = QwenRuntimeConfig(provider="qwen", model=qwen_model)
        
        full_tool_args = ""
        tool_call_found = False
        
        try:
            async for event in service.stream_reply(config, payload):
                if event.event_type == StreamEventType.TOOL_CALL_CHUNK:
                    print(f"🛠️ Tool Call Chunk: {event.args_chunk}", end=" | ", flush=True)
                    full_tool_args += event.args_chunk
                    tool_call_found = True
                elif event.event_type == StreamEventType.MESSAGE_CHUNK:
                    print(event.content, end="", flush=True)
            
            print("\n")
            if tool_call_found:
                print(f"✅ Qwen Requested Tool: {tool_name}")
                print(f"   Args: {full_tool_args}")
                args = json.loads(full_tool_args)
                result = calculate_sum(**args)
                print(f"   Result: {result}")
                assert result == 579
            else:
                print("⚠️ Qwen did not request tool call.")
                
        except Exception as e:
            print(f"\n❌ Qwen Test Failed: {e}")
    else:
        print("Skipping Qwen (not configured)")

    # ==========================
    # Test Gemini
    # ==========================
    print("\n\n🧪 Testing Gemini Tool Use...")
    if "gemini" in llm_manager.providers:
        # Force a capable model
        gemini_model = "gemini-2.0-flash" 
        config = GeminiRuntimeConfig(provider="gemini", model=gemini_model)
        
        full_tool_args = ""
        tool_call_found = False
        
        try:
            async for event in service.stream_reply(config, payload):
                if event.event_type == StreamEventType.TOOL_CALL_CHUNK:
                    # Gemini might return full JSON in one chunk or streaming
                    print(f"🛠️ Tool Call Chunk: {event.args_chunk}", end=" | ", flush=True)
                    full_tool_args += event.args_chunk
                    tool_call_found = True
                elif event.event_type == StreamEventType.MESSAGE_CHUNK:
                    print(event.content, end="", flush=True)
            
            print("\n")
            if tool_call_found:
                print(f"✅ Gemini Requested Tool: {tool_name}")
                print(f"   Args: {full_tool_args}")
                # Gemini args might need cleaning if they come with non-json text? 
                # Usually standard providers give clean JSON args in tool_call chunks.
                args = json.loads(full_tool_args)
                result = calculate_sum(**args)
                print(f"   Result: {result}")
                assert result == 579
            else:
                print("⚠️ Gemini did not request tool call.")

        except Exception as e:
            print(f"\n❌ Gemini Test Failed: {e}")
            import traceback
            traceback.print_exc()
    else:
        print("Skipping Gemini (not configured)")

    await llm_manager.shutdown()

if __name__ == "__main__":
    asyncio.run(test_tool_use())
