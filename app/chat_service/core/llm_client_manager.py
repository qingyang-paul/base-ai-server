from typing import Dict, Any
from app.chat_service.core.llm_providers.base import BaseLLMProvider

class LLMClientManager:
    def __init__(self):
        # 存放所有已注册的 provider
        self.providers: Dict[str, BaseLLMProvider] = {}

    def register(self, provider_name: str, provider: BaseLLMProvider):
        """注册一个新的 LLM 客户端"""
        self.providers[provider_name] = provider
        print(f"Registered LLM provider: {provider_name}")

    async def startup(self):
        """遍历并启动所有已注册的客户端"""
        print("Starting up LLM Client Manager...")
        for name, provider in self.providers.items():
            try:
                await provider.startup()
                print(f"Started provider: {name}")
            except Exception as e:
                print(f"Failed to start provider {name}: {e}")
            
    async def shutdown(self):
        """遍历并关闭所有已注册的客户端"""
        print("Shutting down LLM Client Manager...")
        for name, provider in self.providers.items():
            try:
                await provider.shutdown()
                print(f"Stopped provider: {name}")
            except Exception as e:
                print(f"Failed to stop provider {name}: {e}")

    def get_sdk(self, provider_name: str) -> Any:
        """根据名字获取对应的 SDK"""
        if provider_name not in self.providers:
            raise ValueError(f"未注册的 LLM 提供商: {provider_name}")
        return self.providers[provider_name].get_sdk()

    def get_provider(self, provider_name: str) -> BaseLLMProvider:
        if provider_name not in self.providers:
            raise ValueError(f"未注册的 LLM 提供商: {provider_name}")
        return self.providers[provider_name]

# 全局单例
llm_manager = LLMClientManager()
