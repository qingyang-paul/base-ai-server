import time
from typing import AsyncGenerator
import httpx
from loguru import logger
from openai import AsyncOpenAI
from app.chat_service.core.llm_providers.base import BaseLLMProvider
from app.chat_service.core.config import LLMClientConfig
from app.chat_service.core.schema import (
    GenerationConfig, 
    LLMPayload, 
    StreamReply, 
    MessageChunkEvent, 
    ToolCallChunkEvent,
    StatisticEvent,
    StreamEventType,
    OpenAIRuntimeConfig,
    QwenRuntimeConfig
)
from app.chat_service.core.exceptions import ModelConfigError

class OpenAICompatibleProvider(BaseLLMProvider):
    def __init__(self, config: LLMClientConfig):
        # 接收外部传入的 config，实现配置与逻辑分离
        self.config = config
        self._http_client: httpx.AsyncClient | None = None
        self._sdk: AsyncOpenAI | None = None

    async def startup(self):
        self._http_client = httpx.AsyncClient(
            limits=httpx.Limits(
                max_connections=self.config.limits_max_connections,
                max_keepalive_connections=self.config.limits_keepalive
            ),
            timeout=httpx.Timeout(self.config.timeout)
        )
        
        kwargs = {
            "api_key": self.config.api_key,
            "http_client": self._http_client
        }
        if self.config.base_url:
            kwargs["base_url"] = self.config.base_url
            
        self._sdk = AsyncOpenAI(**kwargs)
        logger.info(f"✅ OpenAI 兼容客户端启动成功 (Base URL: {self.config.base_url or '官方默认'})")

    async def shutdown(self):
        if self._http_client:
            await self._http_client.aclose()
            logger.info("🛑 OpenAI 兼容客户端已关闭")

    def get_sdk(self) -> AsyncOpenAI:
        if not self._sdk:
            raise RuntimeError("SDK 尚未初始化")
        return self._sdk

    async def stream_reply(
        self, 
        config: GenerationConfig, 
        payload: LLMPayload
    ) -> AsyncGenerator[StreamReply, None]:
        
        start_time = time.time()
        seq_id = 0
        output_tokens = 0
        
        # 1. 确保 config 类型正确
        if not isinstance(config, (OpenAIRuntimeConfig, QwenRuntimeConfig)):
             # 如果传入了不匹配的配置，报错
             raise ModelConfigError(f"Invalid config type: {type(config)}. Expected OpenAIRuntimeConfig or QwenRuntimeConfig.")

        # 2. 组装请求参数
        messages_dicts = [m.model_dump(exclude_none=True) for m in payload.messages]
        
        kwargs = {
            "model": config.model,
            "messages": messages_dicts,
            "stream": True,
            "temperature": config.temperature,
            "max_tokens": config.max_tokens,
            "frequency_penalty": config.frequency_penalty
        }
        
        if payload.tools:
            kwargs["tools"] = payload.tools
            if payload.tool_choice:
                kwargs["tool_choice"] = payload.tool_choice

        logger.info(f"Initiating OpenAI stream for model: {config.model}")

        # 3. 发起原生 SDK 请求
        sdk = self.get_sdk()
        try:
            stream = await sdk.chat.completions.create(**kwargs)
        except Exception as e:
            # 这里可以 yield 一个 ERROR 事件，或者直接抛出异常由上层捕获
            raise e

        # 4. 翻译网络流 
        async for chunk in stream:
            delta = chunk.choices[0].delta
            
            # 普通文本
            if delta.content:
                seq_id += 1
                output_tokens += 1 # 粗略估算
                yield MessageChunkEvent(seq_id=seq_id, content=delta.content)
            
            # 工具调用碎片
            if delta.tool_calls:
                for tool_call in delta.tool_calls:
                    seq_id += 1
                    yield ToolCallChunkEvent(
                        seq_id=seq_id,
                        index=tool_call.index,
                        tool_name=tool_call.function.name,
                        args_chunk=tool_call.function.arguments or ""
                    )
        
        # 5. 结束统计 (OpenAI stream 模式下 usage 字段可能需要额外配置 stream_options={"include_usage": True})
        # 为简化，这里先暂略准确 token 统计，或者后续加上
        duration = time.time() - start_time
        yield StatisticEvent(
            seq_id=seq_id + 1,
            input_tokens=0, # 需要 tiktoken 计算或 stream_options
            output_tokens=output_tokens,
            response_duration=duration
        )
