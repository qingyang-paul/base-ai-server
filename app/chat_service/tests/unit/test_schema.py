import pytest
from pydantic import BaseModel, Field
from app.chat_service.chat_service import ChatService
from app.chat_service.core.schema import LLMTool

class WeatherArgs(BaseModel):
    location: str = Field(..., description="City name")
    unit: str = Field(default="celsius", description="Temperature unit")

def test_tool_to_llm_schema():
    service = ChatService()
    
    # Manually create a tool to test schema generation mostly
    # (In integration we depend on registry, here we can test the method directly if public, 
    # but it is private `_tool_to_llm_schema`. We can test it by accessing it or mocking.)
    
    # Or we can just test the standalone function if we refactor, but it is instance method.
    
    tool = LLMTool(
        name="get_weather",
        description="Get weather info",
        args_schema=WeatherArgs,
        func=lambda x: x
    )
    
    schema = service._tool_to_llm_schema(tool)
    
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "get_weather"
    assert schema["function"]["description"] == "Get weather info"
    
    params = schema["function"]["parameters"]
    assert "location" in params["properties"]
    assert "unit" in params["properties"]
    assert "City name" in params["properties"]["location"]["description"]
    assert "required" in params
    assert "location" in params["required"]
