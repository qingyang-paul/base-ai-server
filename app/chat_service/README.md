# Chat Service Module

This module is responsible for the core processing logic of AI chat services, encompassing interactions with major LLM providers (e.g., OpenAI, Gemini, Qwen), local tool (Function Calling) invocations, connection pool management, and streaming response handling.

---

## 1. Module Configuration

The core configuration for this module is located in `app/chat_service/core/config.py`, primarily relying on the Pydantic-based `Settings` model. The system's LLM behavior and various constraints (like model parameters) will be partially or fully delegated to the unified configuration module.

### 1.1 Environment Variable Injection

All client configurations (`LLMClientConfig`) will be automatically extracted from the environment (`.env`) via Pydantic Settings.
Because a nested delimiter is enabled (`env_nested_delimiter='__'`), **double underscores** should be used during configuration:

- `OPENAI__API_KEY=sk-xxxx`
- `GEMINI__API_KEY=AIzaSy...`
- `QWEN__BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1`

### 1.2 Configuration Considerations

- **Configuration Priority and Management**: Ensure that all sensitive data (API Keys) is ONLY input through environment variables. **Hardcoding is strictly prohibited**, otherwise, it will be ignored.
- **Third-Party Proxy Configuration**: If you need to uniformly route through domestic third-party API gateways, you only need to configure the corresponding `[PROVIDER]__BASE_URL` field.
- **Global Parameter Separation**: Unlike specific connection configurations (rate limiting, timeout), the specific generation parameters in an LLM request (like what specific `model name`, `temperature`, etc., are used for the same request) are provided through the global scope `GlobalLLMConfig`. When configuring at the client level, the focus is "how to connect" rather than "what system prompt to use for speaking".

---

## 2. Register LLM Client

The lifecycle (registration, startup, shutdown) of clients is managed by the global singleton `llm_manager` under `app/chat_service/core/llm_client_manager.py`.

### 2.1 Registration Steps

1. **Implement Provider**: Inherit from and implement the `BaseLLMProvider` abstract class (e.g., `OpenAIProvider`, `GeminiProvider`). You must manage the underlying asynchronous client (Async Client) instance yourself and implement related logic in `startup()` and `shutdown()`.
2. **Register to Manager**: During application lifecycle loading (e.g., `lifespan.py`), you need to call `register` to mount the instance:

   ```python
   from app.chat_service.core.llm_client_manager import llm_manager
   from app.chat_service.core.config import settings
   
   # Instantiate your Provider (requires passing settings)
   my_provider = MyNewAPIProvider(config=settings.my_new_llm)
   
   # Register
   llm_manager.register("my_new_llm", my_provider)
   ```

3. **Retrieve Client for Invocation**: Subsequently, in specific business routes, you can retrieve the underlying specific asynchronous client for sending requests via `llm_manager.get_sdk("my_new_llm")`, or directly call `llm_manager.get_provider(...)` to use the standardized interface wrapper of the Provider.
4. **Automatic Lifecycle Management**: When the program starts and stops, it automatically iterates through and calls the `.startup()` and `.shutdown()` methods of the already registered providers.

---

## 3. Register Tools

This module supports standard Function Calling tool mounting, centrally unified and dispatched by the global registry (`registry`) in `app/chat_service/core/llm_tools.py`.

### 3.1 Registration Steps

1. **Register Unique Enum**: First, a new tool identifier must be appended to the `FuncName` enumeration.

   ```python
   class FuncName(str, Enum):
       # ...
       NEW_FEATURE_TOOL = "new_feature_tool"
   ```

2. **Define Pydantic Input Schema**: Clearly express to the LLM what formatted JSON parameters are required to be output if this tool is called.

   ```python
   from pydantic import BaseModel, Field
   class NewFeatureArgs(BaseModel):
       query: str = Field(..., description="Query statement searched by the user")
   ```

3. **Mark Implementation Function with `@registry.register`**: Mount the method to be provided to the AI, making it addressable.

   ```python
   from app.chat_service.core.llm_tools import registry, FuncName
   
   @registry.register(
       name=FuncName.NEW_FEATURE_TOOL.value,
       description="When a user asks for XX information, use this tool to search for data.",
       args_schema=NewFeatureArgs
   )
   async def handle_new_feature(query: str):
       # Specific background business logic
       return {"status": "success", "result": f"Answer for {query}"}
   ```

After registration is complete, when sending the Prompt supporting functions to the LLM, its schema can be automatically serialized and extracted via `registry.get_tool(...)` to be sent over. When the LLM chooses to call the tool, the system reversely executes the mounted async function.
