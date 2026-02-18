import pytest
import json
from pydantic import BaseModel
from app.chat_service.chat_service import ChatService
from app.chat_service.core.llm_tools import registry

# Define schema and tool for testing
class AddArgs(BaseModel):
    a: int
    b: int

class ContextArgs(BaseModel):
    data: str

# We need to register tools in the GLOBAL registry for ChatService to pick them up
@registry.register("add_numbers", "Add two numbers", AddArgs)
def add_numbers(a: int, b: int):
    return a + b

@registry.register("context_tool", "Tool needing context", ContextArgs)
def context_tool(data: str, user_id: str):
    return f"{data}-{user_id}"

@pytest.mark.asyncio
async def test_run_simple_tool():
    service = ChatService()
    
    args = json.dumps({"a": 10, "b": 20})
    result = await service.run_tool("add_numbers", args)
    
    assert result == "30"

@pytest.mark.asyncio
async def test_run_tool_with_context():
    service = ChatService()
    
    args = json.dumps({"data": "hello"})
    context = {"user_id": "user123"}
    
    result = await service.run_tool("context_tool", args, context_kwargs=context)
    
    assert result == "hello-user123"

@pytest.mark.asyncio
async def test_run_unknown_tool():
    service = ChatService()
    result = await service.run_tool("unknown", "{}")
    assert "not found" in result

@pytest.mark.asyncio
async def test_run_tool_invalid_json():
    service = ChatService()
    result = await service.run_tool("add_numbers", "{invalid_json")
    assert "Invalid JSON" in result

@pytest.mark.asyncio
async def test_run_tool_validation_error():
    service = ChatService()
    args = json.dumps({"a": "not_an_int", "b": 20})
    result = await service.run_tool("add_numbers", args)
    assert "validation failed" in result
