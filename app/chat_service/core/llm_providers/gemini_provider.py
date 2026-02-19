import time
import json
from typing import AsyncGenerator, List, Dict, Any
from loguru import logger

# V2 SDK
from google import genai
from google.genai import types

# 内部模块
from app.chat_service.core.llm_providers.base import BaseLLMProvider
from app.chat_service.core.llm_providers.gemini_translator import GeminiTranslator
from app.chat_service.core.config import LLMClientConfig
from app.chat_service.core.schema import (
    GenerationConfig, 
    LLMPayload, 
    StreamReply, 
    MessageChunkEvent, 
    ToolCallChunkEvent, 
    StatisticEvent,
    RoleType,
    LLMMessage
)


class GeminiProvider(BaseLLMProvider):
    def __init__(self, config: LLMClientConfig):
        self.config = config
        self.client = None

    async def startup(self):
        """
        初始化 Gemini SDK Client
        """
        # SDK v2 / google-genai 使用 Client 实例
        # http_options 可以用来配置 transport (e.g. timeout)
        self.client = genai.Client(
            api_key=self.config.api_key
            # http_options={'api_version': 'v1alpha'} # Removed to use default (v1beta/v1)
        )
        logger.info(f"✅ Gemini Client (google-genai) 初始化完成")

    async def shutdown(self):
        """Gemini SDK Client cleanup if needed"""
        pass

    def get_sdk(self) -> Any:
        return genai

    async def stream_reply(
        self, 
        config: GenerationConfig, 
        payload: LLMPayload
    ) -> AsyncGenerator[StreamReply, None]:
        
        start_time = time.time()
        seq_id = 0
        output_tokens = 0
        
        # 1. === 协议转换 ===
        contents = GeminiTranslator.build_history(payload.messages)
        
        # 2. === 准备生成配置 ===
        # 使用 Translator 转换基础配置
        gemini_config = GeminiTranslator.convert_generation_config(config)
        
        # 注入 system_instruction 和 tools 到 config 中
        gemini_config.system_instruction = GeminiTranslator.extract_system_instruction(payload.messages)
        gemini_config.tools = GeminiTranslator.convert_tools(payload.tools) if payload.tools else None
        
        # 3. === 发起流式请求 ===
        try:
            # model argument in new SDK
            # Use .aio for async operations
            response_stream = await self.client.aio.models.generate_content_stream(
                model=config.model,
                contents=contents,
                config=gemini_config
            )

            # 5. === 协议转换：Gemini Chunk -> StreamReply ===
            async for chunk in response_stream:
                # New SDK chunk structure
                # chunk.candidates[0].content.parts[...]
                
                if not chunk.candidates:
                     continue
                     
                for part in chunk.candidates[0].content.parts:
                    # A. 处理普通文本
                    if part.text:
                        seq_id += 1
                        output_tokens += 1
                        yield MessageChunkEvent(seq_id=seq_id, content=part.text)
                    
                    # B. 处理工具调用
                    if part.function_call:
                        fc = part.function_call
                        tool_name = fc.name
                        # New SDK args is already a dict usually, or we access it
                        # If args is raw, might need parsing, but usually it's dict-like
                        args_dict = fc.args
                        if not isinstance(args_dict, dict):
                            # fallback if it's some wrapper
                            try:
                                args_dict = dict(args_dict) 
                            except:
                                args_dict = {}

                        args_json = json.dumps(args_dict, ensure_ascii=False)
                        
                        vendor_extra = {}
                        # In new SDK, we hope it's preserved in some field.
                        
                        seq_id += 1
                        yield ToolCallChunkEvent(
                            seq_id=seq_id,
                            tool_name=tool_name,
                            args_chunk=args_json,
                            index=0, 
                            vendor_extra_chunk=vendor_extra
                        )

            # 6. === 结束统计 ===
            yield StatisticEvent(
                seq_id=seq_id + 1,
                input_tokens=0, 
                output_tokens=output_tokens,
                response_duration=time.time() - start_time
            )

        except Exception as e:
            logger.error(f"Gemini API Error: {str(e)}")
            raise e