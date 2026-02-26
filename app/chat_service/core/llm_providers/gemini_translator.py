import json
from typing import List, Dict, Any, Optional
from google import genai
from google.genai import types

from app.chat_service.core.schema import (
    LLMMessage, 
    RoleType
)
from app.subscription_service.core.config import GlobalLLMConfig
from app.chat_service.core.config import settings

class GeminiTranslator:
    @staticmethod
    def extract_system_instruction(messages: List[LLMMessage]) -> str | None:
        """
        Extracts system instruction from the message list.
        Concatenates multiple system messages if present.
        """
        system_instruction = None
        for msg in messages:
            if msg.role == RoleType.SYSTEM:
                if system_instruction is None:
                    system_instruction = msg.content
                else:
                    system_instruction += f"\n{msg.content}"
        return system_instruction

    @staticmethod
    def build_history(messages: List[LLMMessage]) -> List[types.Content]:
        """
        Converts internal LLMMessages to Gemini content format.
        Skips SYSTEM messages as they are handled via extract_system_instruction.
        """
        gemini_contents = []

        for msg in messages:
            # Skip System Prompt (handled separately)
            if msg.role == RoleType.SYSTEM:
                continue

            # 1. User Message
            if msg.role == RoleType.USER:
                gemini_contents.append(types.Content(
                    role="user",
                    parts=[types.Part.from_text(text=msg.content)]
                ))
                continue

            # 2. Assistant Message (Model)
            if msg.role == RoleType.ASSISTANT:
                parts = []
                # Normal text response
                if msg.content:
                    parts.append(types.Part.from_text(text=msg.content))
                
                # Tool Call Request (OpenAI -> Gemini)
                if msg.tool_calls:
                    for tc in msg.tool_calls:
                        # Construct Gemini function_call part
                        fc_data = {
                            "name": tc.function.name,
                            "args": json.loads(tc.function.arguments) # Must pass dict
                        }
                        # Restore vendor specific fields (e.g. thought_signature)
                        if tc.function.vendor_extra:
                             # Explicitly whitelist known fields
                             for k, v in tc.function.vendor_extra.items():
                                 if k in ['thought_signature']:
                                     fc_data[k] = v
                        
                        parts.append(types.Part.from_function_call(
                            name=fc_data["name"],
                            args=fc_data["args"]
                        ))
                
                gemini_contents.append(types.Content(
                    role="model",
                    parts=parts
                ))
                continue

            # 3. Tool Result (Function Response)
            if msg.role == RoleType.TOOL:
                # Gemini needs to know which function name this result is for.
                # Assuming msg.name is populated from schema validation.
                tool_name = msg.name 
                
                # Construct response content (dict)
                try:
                    parsed = json.loads(msg.content)
                    if isinstance(parsed, dict):
                         response_content = parsed
                    else:
                         # Wrap primitives in a dict
                         # Note: In new SDK, strict dict check is usually enforced
                         response_content = {"result": parsed}
                except:
                    # Not JSON, wrap string
                    response_content = {"result": msg.content}

                gemini_contents.append(types.Content(
                    role="tool", # Changed to tool role in new SDK? Or stick to user? Let's check docs or keep as user/tool based on usage. 
                                 # In new SDK, tool responses are typically role='tool' or associated with function response part.
                                 # Let's try 'user' for now as per old behavior, but if it fails we switch.
                                 # Actually, the new SDK documentation often suggests 'tool' role for function responses.
                                 # BUT the content structure is `parts=[types.Part.from_function_response(...)]`
                    parts=[types.Part.from_function_response(
                        name=tool_name,
                        response=response_content
                    )]
                ))
                continue
        
        return gemini_contents

    @staticmethod
    def _clean_schema(schema: Any) -> Any:
        """
        Helper to clean JSON schema for Gemini Protobuf compatibility.
        1. Recursively removes 'title'
        2. Uppercases 'type' values (integer -> INTEGER)
        """
        if isinstance(schema, dict):
            new_schema = {}
            for k, v in schema.items():
                if k == "title":
                    continue
                
                if k == "type" and isinstance(v, str):
                    new_schema[k] = v.upper()
                else:
                    new_schema[k] = GeminiTranslator._clean_schema(v)
            return new_schema
            
        elif isinstance(schema, list):
            return [GeminiTranslator._clean_schema(item) for item in schema]
            
        return schema

    @staticmethod
    def convert_tools(openai_tools: List[Dict[str, Any]]) -> Optional[List[types.Tool]]:
        """
        Converts OpenAI tool definitions to Gemini function declarations.
        """
        if not openai_tools:
            return None

        function_declarations = []
        for t in openai_tools:
            if t.get("type") == "function":
                f_schema = t["function"]
                
                if "parameters" in f_schema:
                    f_schema["parameters"] = GeminiTranslator._clean_schema(f_schema["parameters"])
                
                function_declarations.append(types.FunctionDeclaration(
                    name=f_schema.get("name"),
                    description=f_schema.get("description"),
                    parameters=f_schema.get("parameters")
                ))
        
        # New SDK takes list of tools, where each tool has function_declarations
        return [types.Tool(function_declarations=function_declarations)]

    @staticmethod
    def convert_generation_config(config: GlobalLLMConfig) -> types.GenerateContentConfig:
        """
        Converts internal GlobalLLMConfig to Gemini's types.GenerateContentConfig.
        """
        return types.GenerateContentConfig(
            temperature=config.temperature,
            max_output_tokens=config.max_tokens_per_request,
            # Add other fields as needed
        )
