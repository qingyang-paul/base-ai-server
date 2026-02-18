from typing import List, Dict, Any, Optional, Union
import json
import asyncio
from app.chat_service.core.llm_tools import registry, FuncName
from app.chat_service.core.schema import (
    LLMTool, RoleType, LLMMessage, ChatHistory, LLMPayload, UserQuery, SessionContext, SOPPreference
)

class ChatService:
    def __init__(self):
        self.tools = registry.tools

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
            return f"Error: Tool '{tool_name}' not found."

        try:
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
            return f"Error executing tool '{tool_name}': {str(e)}"
