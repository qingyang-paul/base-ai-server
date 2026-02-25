import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.chat_service.core.config import LLMClientConfig, Settings
from app.chat_service.core.llm_client_manager import LLMClientManager
from app.chat_service.core.llm_providers.openai_provider import OpenAICompatibleProvider
from app.chat_service.core.llm_providers.gemini_provider import GeminiProvider

# ==========================
# Config Tests
# ==========================

def test_llm_client_config():
    config = LLMClientConfig(
        api_key="sk-test", 
        base_url="http://test.com",
        model="gpt-4-test"
    )
    assert config.api_key == "sk-test"
    assert config.base_url == "http://test.com"
    assert config.timeout == 30.0 # default

# ==========================
# Manager Tests
# ==========================

@pytest.mark.asyncio
async def test_llm_manager_registration_and_lifecycle():
    manager = LLMClientManager()
    mock_provider = AsyncMock()
    
    manager.register("test_provider", mock_provider)
    assert manager.get_provider("test_provider") == mock_provider
    
    await manager.startup()
    mock_provider.startup.assert_awaited_once()
    
    await manager.shutdown()
    mock_provider.shutdown.assert_awaited_once()

def test_llm_manager_get_sdk():
    manager = LLMClientManager()
    mock_provider = MagicMock()
    mock_provider.get_sdk.return_value = "mock_sdk"
    
    manager.register("test", mock_provider)
    assert manager.get_sdk("test") == "mock_sdk"

def test_llm_manager_get_sdk_not_found():
    manager = LLMClientManager()
    with pytest.raises(ValueError):
        manager.get_sdk("non_existent")

# ==========================
# OpenAI Provider Tests
# ==========================

@pytest.mark.asyncio
async def test_openai_provider_startup_shutdown():
    config = LLMClientConfig(
        api_key="sk-test",
        model="gpt-4-test"
    )
    provider = OpenAICompatibleProvider(config)
    
    with patch("app.chat_service.core.llm_providers.openai_provider.httpx.AsyncClient") as mock_client_cls, \
         patch("app.chat_service.core.llm_providers.openai_provider.AsyncOpenAI") as mock_openai_cls:
        
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client
        
        await provider.startup()
        
        assert provider._http_client is not None
        assert provider._sdk is not None
        mock_openai_cls.assert_called_once()
        
        await provider.shutdown()
        mock_client.aclose.assert_awaited_once()

# ==========================
# Gemini Provider Tests
# ==========================

@pytest.mark.asyncio
async def test_gemini_provider_startup():
    config = LLMClientConfig(
        api_key="test-key",
        model="gpt-4-test"
    )
    provider = GeminiProvider(config)
    
    with patch("app.chat_service.core.llm_providers.gemini_provider.genai") as mock_genai:
        await provider.startup()
        mock_genai.Client.assert_called_with(api_key="test-key")
        assert provider.get_sdk() == mock_genai
