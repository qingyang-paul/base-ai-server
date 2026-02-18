from typing import List, Dict, Any, Optional
import json
import asyncio
from app.chat_service.core.llm_tools import registry
from app.chat_service.core.schema import LLMTool

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
