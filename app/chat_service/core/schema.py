from dataclasses import dataclass
from typing import Callable, Type, Any
from pydantic import BaseModel

@dataclass
class LLMTool:
    name: str
    description: str
    args_schema: Type[BaseModel]
    func: Callable[..., Any]
