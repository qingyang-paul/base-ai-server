import pytest
from pydantic import BaseModel
from app.chat_service.core.llm_tools import ToolRegistry

class MockArgs(BaseModel):
    arg1: str

def test_register_tool():
    registry = ToolRegistry()
    
    @registry.register(name="test_tool", description="A test tool", args_schema=MockArgs)
    def test_func(arg1: str):
        return arg1
        
    assert "test_tool" in registry.tools
    tool = registry.get_tool("test_tool")
    assert tool.name == "test_tool"
    assert tool.description == "A test tool"
    assert tool.args_schema == MockArgs
    assert tool.func == test_func

def test_get_nonexistent_tool():
    registry = ToolRegistry()
    assert registry.get_tool("nonexistent") is None
