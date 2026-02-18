import time
import json
import logging
from typing import AsyncGenerator, List, Dict, Any

# 官方 SDK
import google.generativeai as genai
from google.generativeai.types import (
    HarmCategory, 
    HarmBlockThreshold, 
    ContentDict,
    FunctionDeclaration,
    Tool as GeminiTool
)
from google.protobuf.struct_pb2 import Struct

# 内部模块
from app.chat_service.core.llm_providers.base import BaseLLMProvider
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

logger = logging.getLogger(__name__)

class GeminiProvider(BaseLLMProvider):
    def __init__(self, config: LLMClientConfig):
        self.config = config
        self._model = None

    async def startup(self):
        """
        初始化 Gemini SDK
        注意：Google SDK 内部管理连接池，通常不需要像 httpx 那样显式初始化 Client，
        但在 v1.0+ SDK 中可能有 Client 对象。这里演示标准配置方式。
        """
        # 配置 API KEY
        genai.configure(api_key=self.config.api_key)
        
        # 如果需要自定义 Base URL (例如通过 Vertex AI 或代理)，通常在大模型实例化时指定
        # 或通过 transport 调整，此处演示最通用的 setup
        print(f"✅ Gemini 客户端配置完成")

    async def shutdown(self):
        """Gemini SDK 通常不需要显式关闭连接"""
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
        
        # 1. === 协议转换：OpenAI Payload -> Gemini Contents ===
        system_instruction, contents = self._convert_messages_to_gemini(payload.messages)
        tools = self._convert_tools_to_gemini(payload.tools) if payload.tools else None
        
        # 2. === 初始化模型 ===
        # 实例化模型对象
        model = genai.GenerativeModel(
            model_name=config.model,
            system_instruction=system_instruction,
            tools=tools
        )

        # 3. === 准备生成配置 ===
        generation_config = genai.GenerationConfig(
            temperature=config.temperature,
            # max_output_tokens=config.max_output_tokens, # 如果你的 config 里有这个字段
            # top_k=config.top_k, 
        )

        # 4. === 发起流式请求 ===
        try:
            # send_message (chat 模式) vs generate_content (单轮模式)
            # 为了处理历史记录，这里使用 generate_content 并传入完整 contents 列表
            response_stream = await model.generate_content_async(
                contents,
                generation_config=generation_config,
                stream=True
            )

            # 5. === 协议转换：Gemini Chunk -> StreamReply ===
            async for chunk in response_stream:
                # Gemini 的 chunk 可能包含 text，也可能包含 function_call
                
                # A. 处理普通文本
                # 注意：Gemini 有时会因为安全原因返回空 text，需判空
                if chunk.candidates and chunk.candidates[0].content.parts:
                    part = chunk.candidates[0].content.parts[0]
                    
                    if part.text:
                        seq_id += 1
                        output_tokens += 1 # 粗略估算
                        yield MessageChunkEvent(seq_id=seq_id, content=part.text)
                    
                    # B. 处理工具调用
                    # Gemini 通常会在一个 chunk 里返回完整的 function_call，而不是像 OpenAI 那样分片
                    # 但为了兼容我们的 ToolCallAccumulator，我们一次性把 JSON 发过去
                    if part.function_call:
                        fc = part.function_call
                        tool_name = fc.name
                        # 将 protobuf Struct 转为 dict 再转 JSON 字符串
                        # 这是一个完整的 JSON，我们作为 args_chunk 发送
                        args_dict = dict(fc.args)
                        args_json = json.dumps(args_dict, ensure_ascii=False)
                        
                        seq_id += 1
                        yield ToolCallChunkEvent(
                            seq_id=seq_id,
                            tool_name=tool_name,
                            args_chunk=args_json,
                            index=0 # Gemini 通常一次只调一个工具，或 SDK 处理方式不同，这里默认 index=0
                        )

            # 6. === 结束统计 ===
            yield StatisticEvent(
                seq_id=seq_id + 1,
                input_tokens=0, # 需调用 count_tokens API 获取精准值
                output_tokens=output_tokens,
                response_duration=time.time() - start_time
            )

        except Exception as e:
            logger.error(f"Gemini API Error: {str(e)}")
            # 这里可以选择 yield 一个 ErrorEvent 或者直接抛出
            # 为了 Agent Loop 的健壮性，抛出异常让上层处理可能更好
            raise e

    # =========================================================
    # 私有辅助方法：协议适配器 (Adapter Pattern)
    # =========================================================

    def _convert_messages_to_gemini(self, messages: List[LLMMessage]):
        """
        将 OpenAI 格式的消息列表转换为 Gemini 的 contents 和 system_instruction
        OpenAI: role = system, user, assistant, tool
        Gemini: role = user, model (无 system, system 需单独提取; tool 结果需转为 function_response)
        """
        system_instruction = None
        gemini_contents = []

        for msg in messages:
            # 1. 提取 System Prompt
            if msg.role == RoleType.SYSTEM:
                # 如果有多个 system，拼接起来
                if system_instruction is None:
                    system_instruction = msg.content
                else:
                    system_instruction += f"\n{msg.content}"
                continue

            # 2. User Message
            if msg.role == RoleType.USER:
                gemini_contents.append({
                    "role": "user",
                    "parts": [{"text": msg.content}]
                })
                continue

            # 3. Assistant Message (Model)
            if msg.role == RoleType.ASSISTANT:
                parts = []
                # 普通回复
                if msg.content:
                    parts.append({"text": msg.content})
                
                # 工具调用请求 (OpenAI 格式 -> Gemini 格式)
                if msg.tool_calls:
                    for tc in msg.tool_calls:
                        # 构造 Gemini 的 function_call part
                        parts.append({
                            "function_call": {
                                "name": tc.function.name,
                                "args": json.loads(tc.function.arguments) # 必须传 dict，Gemini SDK 会自动转 protobuf
                            }
                        })
                
                gemini_contents.append({
                    "role": "model",
                    "parts": parts
                })
                continue

            # 4. Tool Result (Function Response)
            if msg.role == RoleType.TOOL:
                # OpenAI: role=tool, tool_call_id=..., content=result
                # Gemini: role=function, parts=[{function_response: {name:..., response:...}}]
                
                # 注意：Gemini 需要知道这个结果对应哪个函数名。
                # 但 OpenAI 的 standard message 里，tool result 通常只有 tool_call_id。
                # 我们在 LLMMessage DTO 里加了 `name` 字段，这对 Gemini 适配至关重要！
                
                tool_name = msg.name # 必须从之前的上下文或 DTO 中获取
                
                # 构造响应内容 (dict)
                try:
                    # 尝试把内容解析为 JSON 对象，因为 Gemini response 最好是结构化的
                    response_content = json.loads(msg.content)
                except:
                    # 如果不是 JSON，就包一层
                    response_content = {"result": msg.content}

                gemini_contents.append({
                    "role": "user", # Gemini 的 function_response 通常归类为 user 端的数据注入
                    "parts": [{
                        "function_response": {
                            "name": tool_name,
                            "response": response_content
                        }
                    }]
                })
                continue

        return system_instruction, gemini_contents

    def _convert_tools_to_gemini(self, openai_tools: List[Dict[str, Any]]):
        """
        将 OpenAI JSON Schema 格式的 tools 转换为 Gemini Tool 对象
        """
        # Gemini Python SDK 现在的做法比较灵活，
        # 如果传入的是标准 function declaration 字典，SDK 会尝试自动转换。
        # 这里我们直接透传 OpenAI 格式的 tools list 给 SDK，
        # 如果版本兼容性有问题，需要在这里手动构造 genai.types.FunctionDeclaration
        
        # 简单处理：Gemini 接受的 tools 是一个 Tool 对象列表或 FunctionDeclaration 列表
        # OpenAI 格式: {"type": "function", "function": {...}}
        
        gemini_functions = []
        for t in openai_tools:
            if t.get("type") == "function":
                f_schema = t["function"]
                # 构造 Gemini FunctionDeclaration
                # 注意：OpenAI parameters 是 standard JSON Schema
                # Gemini 同样支持，但需确保字段映射正确
                
                if "parameters" in f_schema:
                    f_schema["parameters"] = self._clean_schema(f_schema["parameters"])
                
                gemini_functions.append(f_schema)
        
        # 包装成 Gemini Tool 对象
        return gemini_functions

    def _clean_schema(self, schema: Dict[str, Any]) -> Dict[str, Any]:
        """
        1. 递归移除 'title' 字段
        2. 将 'type' 字段的值转为大写 (integer -> INTEGER) 以适配 Gemini Protobuf Enum
        """
        if isinstance(schema, dict):
            new_schema = {}
            for k, v in schema.items():
                if k == "title":
                    continue
                
                if k == "type" and isinstance(v, str):
                    # Gemini/Protobuf 比较严格，通常需要大写
                    new_schema[k] = v.upper()
                else:
                    new_schema[k] = self._clean_schema(v)
            return new_schema
            
        if isinstance(schema, list):
            return [self._clean_schema(item) for item in schema]
            
        return schema