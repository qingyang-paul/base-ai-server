import asyncio
import pytest
import os
import sys
from dotenv import load_dotenv

# Ensure project root is in path
sys.path.insert(0, os.getcwd())

# Load environment variables
load_dotenv()

from app.chat_service.core.config import settings
from app.chat_service.core.llm_client_manager import llm_manager
from app.chat_service.core.llm_providers.openai_provider import OpenAICompatibleProvider
from app.chat_service.core.llm_providers.gemini_provider import GeminiProvider
from app.chat_service.chat_service import ChatService
from app.chat_service.core.schema import (
    LLMPayload, UserQuery, ChatHistory, GeminiRuntimeConfig, OpenAIRuntimeConfig, QwenRuntimeConfig,
    StreamEventType, MessageChunkEvent, ToolCallChunkEvent, RoleType
)

@pytest.mark.asyncio
async def test_providers():
    print("🚀 Starting Integration Test for Chat Service Providers")
    
    # 1. Setup Manager (Mimics lifespan logic but safe)
    print("--- Setting up LLM Manager ---")
    
    # Register Gemini
    if hasattr(settings, 'gemini') and settings.gemini:
        print(f"Registering Gemini Provider with model: {settings.gemini.model}")
        llm_manager.register("gemini", GeminiProvider(settings.gemini))
    else:
        print("❌ Gemini settings not found")

    # Register Qwen
    if hasattr(settings, 'qwen') and settings.qwen:
        print(f"Registering Qwen Provider with output model: {settings.qwen.model}")
        llm_manager.register("qwen", OpenAICompatibleProvider(settings.qwen))
    else:
        print("❌ Qwen settings not found")

    await llm_manager.startup()
    
    service = ChatService()

    # 2. Test Qwen (Run first as it might be more stable)
    print("\n\n🧪 Testing Qwen Provider...")
    if "qwen" in llm_manager.providers:
        payload = LLMPayload(
            messages=[
                UserQuery(content="Hello Qwen! Please introduce yourself.")
            ]
        )
        
        # For Qwen, we now use QwenRuntimeConfig
        qwen_model = settings.qwen.model if hasattr(settings, 'qwen') and settings.qwen.model else "qwen-max"
        
        config = QwenRuntimeConfig(
            provider="qwen", 
            model=qwen_model
        )
        
        print(f"Calling Qwen with model: {config.model}")
        try:
            async for event in service.stream_reply(config, payload):
                if event.event_type == StreamEventType.MESSAGE_CHUNK:
                    print(event.content, end="", flush=True)
                elif event.event_type == StreamEventType.ERROR:
                    print(f"\nError: {event.content}")
            print("\n✅ Qwen Test Completed")
        except Exception as e:
            print(f"\n❌ Qwen Test Failed: {e}")
            import traceback
            traceback.print_exc()
    else:
        print("Skipping Qwen test (provider not registered)")
    
    # 3. Test Gemini
    print("\n\n🧪 Testing Gemini Provider...")
    if "gemini" in llm_manager.providers:
        payload = LLMPayload(
            messages=[
                UserQuery(content="Hello Gemini! What is your name and what model are you?")
            ]
        )
        
        # Determine model to use (from settings or default in schema)
        # We need to construct the runtime config carefully
        gemini_model = "gemini-2.0-flash" # Force use a known working model for testing
        
        config = GeminiRuntimeConfig(
            provider="gemini",
            model=gemini_model
        )
        
        print(f"Calling Gemini with model: {config.model}")
        try:
            async for event in service.stream_reply(config, payload):
                if event.event_type == StreamEventType.MESSAGE_CHUNK:
                    print(event.content, end="", flush=True)
                elif event.event_type == StreamEventType.ERROR:
                    print(f"\nError: {event.content}")
            print("\n✅ Gemini Test Completed")
        except Exception as e:
            print(f"\n❌ Gemini Test Failed: {e}")
    else:
        print("Skipping Gemini test (provider not registered)")

    await llm_manager.shutdown()

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(test_providers())
