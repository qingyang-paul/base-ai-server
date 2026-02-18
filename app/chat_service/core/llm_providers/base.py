from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator

from app.chat_service.core.schema import GenerationConfig, LLMPayload, StreamReply


class BaseLLMProvider(ABC):
    """所有 LLM 客户端的统一抽象基类"""

    @abstractmethod
    async def startup(self):
        """初始化连接池和 SDK"""
        pass

    @abstractmethod
    async def shutdown(self):
        """关闭连接池释放资源"""
        pass

    @abstractmethod
    def get_sdk(self) -> Any:
        """返回实例化后的官方 SDK"""
        pass

    @abstractmethod
    async def stream_reply(
        self, config: GenerationConfig, payload: LLMPayload
    ) -> AsyncGenerator[StreamReply, None]:
        """
        接收标准参数，返回标准事件流。
        具体怎么和第三方 SDK 交互，怎么拆解流，由各个子类自己决定！
        """
        pass
