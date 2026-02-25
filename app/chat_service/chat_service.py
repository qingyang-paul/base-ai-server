from typing import List, Dict, Any, Optional, Union, AsyncGenerator
import json
import asyncio
from loguru import logger
from app.chat_service.core.llm_tools import registry, FuncName
from app.chat_service.core.schema import (
    LLMTool, RoleType, LLMMessage, ChatHistory, LLMPayload, UserQuery, SessionContext, SOPPreference,
    GenerationConfig, StreamReply, StatusEvent, StreamEventType, ToolCallChunkEvent, MessageChunkEvent, ToolCall, ToolCallFunction, StatisticEvent, RunFinishEvent
)
from app.chat_service.core.config import settings
from app.chat_service.core.llm_client_manager import llm_manager

from app.chat_service.core.exceptions import ProviderNotFoundError

import time
class ChatService:
    def __init__(self):
        self.tools = registry.tools

    async def stream_reply(
        self, 
        runtime_config: GenerationConfig, 
        payload: LLMPayload
    ) -> AsyncGenerator[StreamReply, None]:
        """
        极其纯净的代理层。根据请求的提供商，直接将任务分发给对应的 Provider 插件。
        """
        
        # 1. 从注册中心获取对应的业务处理插件（比如 OpenAICompatibleProvider）
        provider_name = runtime_config.provider
        
        try:
           provider = llm_manager.get_provider(provider_name)
        except ValueError:
            raise ProviderNotFoundError(f"Provider '{provider_name}' not found. Available: {list(llm_manager.providers.keys())}")
        
        # 2. 调用插件的 stream_reply 方法，原样透传给上层
        logger.info(f"Using provider: {provider_name} for model: {runtime_config.model}")
        try:
            async for event in provider.stream_reply(config=runtime_config, payload=payload):
                yield event
        except Exception as e:
            logger.error(f"Stream reply failed: {e}")
            raise e

    def _tool_to_llm_schema(self, tool: LLMTool) -> Dict[str, Any]:
        """Convert LLMTool to OpenAI function schema format."""
        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.args_schema.model_json_schema(),
            }
        }

    def build_llm_payload(
        self,
        system_prompt: str,
        chat_history: ChatHistory,
        user_query: UserQuery,
        session_context: SessionContext,
        allowed_tools: List[FuncName]
    ) -> LLMPayload:
        """
        Assemble the payload for LLM from history, query, and context.
        Levels:
        1. Inject SOP preferences into system prompt.
        2. Combine System + History + UserQuery.
        3. Filter and Format Tools.
        """
        # 1. Inject SOP preferences
        final_system_prompt = system_prompt
        if session_context.user_sop_preferences:
            sop_text = "\n\nUser SOP Preferences:\n"
            for sop in session_context.user_sop_preferences:
                sop_text += f"- [{sop.subject}]: {sop.content}\n"
            final_system_prompt += sop_text

        # 2. Assemble Messages
        messages: List[LLMMessage] = []
        
        # System Message
        messages.append(LLMMessage(role=RoleType.SYSTEM, content=final_system_prompt))
        
        # History
        messages.extend(chat_history.messages)
        
        # User Query
        # Note: UserQuery is a subclass of LLMMessage, but we might want to ensure it's treated as one.
        # It has role=USER fixed.
        messages.append(user_query)

        # 3. Handle Tools
        llm_tools = []
        for tool_name in allowed_tools:
            # tool_name is enum FuncName, but registry keys are strings (values of enum)
            # FuncName is str Enum, so iterating it gives values? No, List[FuncName] gives Enum members.
            # We need the value.
            name_str = tool_name.value if hasattr(tool_name, 'value') else tool_name
            tool = self.tools.get(name_str)
            if tool:
                llm_tools.append(self._tool_to_llm_schema(tool))
        
        return LLMPayload(
            messages=messages,
            tools=llm_tools if llm_tools else None,
            tool_choice="auto" if llm_tools else None
        )


    async def run_tool(self, tool_name: str, args_json: str, context_kwargs: Dict[str, Any] = None) -> str:
        """
        Execute a registered tool.
        
        Args:
            tool_name: The name of the tool to execute.
            args_json: The arguments for the tool as a JSON string.
            context_kwargs: Additional context to inject into the tool (e.g., user_id).
        
        Returns:
            The result of the tool execution as a string.
        """
        if context_kwargs is None:
            context_kwargs = {}

        tool = self.tools.get(tool_name)
        if not tool:
            logger.warning(f"Tool '{tool_name}' not found.")
            return f"Error: Tool '{tool_name}' not found."

        try:
            logger.info(f"Executing tool: {tool_name} with args: {args_json}")
            # 1. Parse arguments (JSON string -> Dict)
            try:
                args_dict = json.loads(args_json)
            except json.JSONDecodeError:
                return f"Error: Invalid JSON arguments for tool '{tool_name}'."

            # 2. Validate arguments against schema
            try:
                validated_args = tool.args_schema(**args_dict)
            except Exception as e:
                return f"Error: Argument validation failed for tool '{tool_name}': {str(e)}"

            # 3. Prepare function arguments
            # Filter args_dict to only include what's in the schema serves as a double check, 
            # but pydantic model dump is safer.
            # We also need to inject context_kwargs if the function signature asks for them?
            # For this Level 1 implementation, let's assume context_kwargs are passed 
            # if the tool's function definition has matching arguments, or we handle it via the args_schema
            # BUT, the task.md example implies context args (like user_id) are NOT in the schema but injected.
            # Let's check the function signature or kwargs.
            
            # Simple approach for Level 1:
            # Pass validated_args as keyword arguments.
            # MIXIN context_kwargs? 
            # The example shows `def get_user_orders_api(time_range: str, user_id: str)`.
            # `time_range` comes from LLM (validated_args). `user_id` comes from context.
            
            call_kwargs = validated_args.model_dump()
            
            # We need to inspect the tool.func to see if it accepts context_kwargs keys
            # Or we simply update call_kwargs with context_kwargs and let python handle it (or fail if unexpected arg)
            # A safer way is to inspect signature, but for now let's just merge.
            # Prority: context_kwargs overrides LLM args? Or vice-versa? 
            # Usually context is system-level, so it should probably be separate or merged carefully.
            # The example implies seamless injection.
            call_kwargs.update(context_kwargs)
            
            # 4. Execute function
            if asyncio.iscoroutinefunction(tool.func):
                result = await tool.func(**call_kwargs)
            else:
                result = await asyncio.to_thread(tool.func, **call_kwargs)

            return str(result)

        except Exception as e:
            logger.error(f"Error executing tool '{tool_name}': {e}")
            return f"Error executing tool '{tool_name}': {str(e)}"

    async def chat_stream_with_tools(
        self, runtime_config: GenerationConfig, payload: LLMPayload, context_kwargs: dict = None
    ) -> AsyncGenerator[StreamReply, None]:
        """Level 5: Agentic Loop (Core State Machine)"""
        if context_kwargs is None: context_kwargs = {}
        max_loops = settings.agent_max_loops
        current_payload = payload
        loop_count = 0
        global_seq_id = int(time.time() * 1000)
        
        # 用于记录本次用户query下，涉及的所有LLM生成的信息（工具调用，最终回复）及工具调用结果
        generated_messages: List[LLMMessage] = []
        
        logger.info(f"Starting agent loop for model: {runtime_config.model}")
        
        # Get provider instance
        provider_name = runtime_config.provider
        try:
           provider = llm_manager.get_provider(provider_name)
        except ValueError:
            raise ProviderNotFoundError(f"Provider '{provider_name}' not found. Available: {list(llm_manager.providers.keys())}")

        try:
            while loop_count < max_loops:
                loop_count += 1
                tool_calls_acc = {}
                input_tokens_this_round = 0
                output_tokens_this_round = 0

                if loop_count > 1:
                    global_seq_id += 1
                    yield StatusEvent(seq_id=global_seq_id, message="正在思考总结...", status="running")

                assistant_content = ""
                # Receive standard event stream from provider
                async for event in provider.stream_reply(runtime_config, current_payload):
                    global_seq_id += 1
                    # Override seq_id to ensure global ordering
                    event.seq_id = global_seq_id
                    yield event

                    if isinstance(event, MessageChunkEvent):
                        if event.content:
                            assistant_content += event.content

                    if isinstance(event, StatisticEvent):
                        input_tokens_this_round += event.input_tokens
                        output_tokens_this_round += event.output_tokens

                    if isinstance(event, ToolCallChunkEvent):
                        idx = event.index
                        if idx not in tool_calls_acc:
                            tool_calls_acc[idx] = {
                                "id": f"call_{idx}_{global_seq_id}", 
                                "name": event.tool_name or "", 
                                "arguments": event.args_chunk or "",
                                "vendor_extra": event.vendor_extra_chunk or {}
                            }
                        else:
                            if event.tool_name: tool_calls_acc[idx]["name"] += event.tool_name
                            if event.args_chunk: tool_calls_acc[idx]["arguments"] += event.args_chunk
                            if event.vendor_extra_chunk:
                                if "vendor_extra" not in tool_calls_acc[idx]:
                                    tool_calls_acc[idx]["vendor_extra"] = {}
                                tool_calls_acc[idx]["vendor_extra"].update(event.vendor_extra_chunk)

                if current_payload.messages:
                    current_payload.messages[-1].tokens = input_tokens_this_round

                if not tool_calls_acc:
                     # If we have content but no tools, we should also update history?
                     # Actually, usually if no tools, we break and the loop ends,
                     # 但是需要把最终返回的文字内容也加到记录里面
                     if assistant_content:
                         generated_messages.append(LLMMessage(
                             role=RoleType.ASSISTANT,
                             content=assistant_content,
                             tokens=output_tokens_this_round
                         ))
                     # The caller (client) has received the stream.
                     # The 'payload' is local to this request.
                     break

                 # Execute tools
                assistant_tool_msg = LLMMessage(
                    role=RoleType.ASSISTANT, 
                    content=assistant_content, 
                    tool_calls=[],
                    tokens=output_tokens_this_round
                )
                tool_results_msgs = []

                for idx, data in tool_calls_acc.items():
                    t_name = data["name"]
                    t_args = data["arguments"]
                    t_vendor_extra = data.get("vendor_extra")
                    
                    # Create ToolCall object for history
                    # We need a unique ID for the tool call
                    tool_call_id = data["id"]
                    assistant_tool_msg.tool_calls.append(ToolCall(
                        id=tool_call_id, 
                        function=ToolCallFunction(name=t_name, arguments=t_args, vendor_extra=t_vendor_extra)
                    ))
                    
                    # Get description for display
                    desc = t_name # Default to name
                    tool_def = self.tools.get(t_name)
                    if tool_def:
                        desc = tool_def.description

                    global_seq_id += 1
                    yield StatusEvent(seq_id=global_seq_id, message=f"正在 {desc}...", tool_name=t_name, status="running")
                    
                    # Execute the tool
                    res_str = await self.run_tool(t_name, t_args, context_kwargs)
                    
                    global_seq_id += 1
                    yield StatusEvent(seq_id=global_seq_id, message=f"已完成 {desc}", tool_name=t_name, status="success")
                    
                    tool_results_msgs.append(LLMMessage(role=RoleType.TOOL, tool_call_id=tool_call_id, name=t_name, content=res_str))

                # 更新记录：单次大模型返回的消息（包括中间步骤的回答和tool_calls）和各工具的结果 
                generated_messages.append(assistant_tool_msg)
                generated_messages.extend(tool_results_msgs)

                # Update payload with assistant's tool calls and tool results
                current_payload.messages.append(assistant_tool_msg)
                current_payload.messages.extend(tool_results_msgs)
                
            else:
                # Loop finished without breaking (max loops reached)
                 yield MessageChunkEvent(seq_id=99999, content="\n\n[系统] 操作超限，已强制停止。")

        finally:
            # 在返回或出现异常时，把记录的 generated_messages 列表发送出去
            yield RunFinishEvent(
                seq_id=global_seq_id + 1, 
                generated_messages=generated_messages
            )

