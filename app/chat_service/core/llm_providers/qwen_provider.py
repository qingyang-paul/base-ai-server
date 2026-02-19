from app.chat_service.core.llm_providers.openai_provider import OpenAICompatibleProvider
from app.chat_service.core.config import LLMClientConfig

class QwenProvider(OpenAICompatibleProvider):
    """
    Qwen Provider using OpenAI Compatible API.
    Inherits from OpenAICompatibleProvider but allows for Qwen-specific logic in the future.
    """
    def __init__(self, config: LLMClientConfig):
        super().__init__(config)
        print(f"✅ Qwen 客户端初始化 (Base URL: {self.config.base_url})")

    async def startup(self):
        await super().startup()
        # You could add Qwen-specific startup checks here if needed
