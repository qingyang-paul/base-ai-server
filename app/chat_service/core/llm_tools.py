from enum import Enum
from typing import Dict, Type, Callable, Optional
from loguru import logger
from pydantic import BaseModel
from app.chat_service.core.schema import LLMTool

class FuncName(str, Enum):
    # Example tools, to be expanded
    GET_WEATHER = "get_weather"
    SEARCH_WEB = "search_web"
    GET_USER_ORDERS = "get_user_orders"

class ToolRegistry:
    def __init__(self):
        self.tools: Dict[str, LLMTool] = {}

    def register(self, name: str, description: str, args_schema: Type[BaseModel]):
        """
        Decorator factory to register a tool.
        """
        def decorator(func: Callable):
            tool = LLMTool(
                name=name,
                description=description,
                args_schema=args_schema,
                func=func
            )
            self.tools[name] = tool
            logger.info(f"Registered tool: {name}")
            return func
        return decorator

    def get_tool(self, name: str) -> Optional[LLMTool]:
        return self.tools.get(name)

# Global registry instance
registry = ToolRegistry()
