# Chat Service Module

该模块负责聊天服务的核心逻辑（单次请求），包括 LLM 交互、工具调用、流式响应等。

## 1. 注册新工具 (Add New Tool)

要注册一个新的工具供 LLM 使用，需要完成以下步骤：

### 1.1 定义枚举名称

在 `app/chat_service/core/llm_tools.py` 中，向 `FuncName` 枚举添加新的工具名称。

```python
# app/chat_service/core/llm_tools.py

class FuncName(str, Enum):
    # ... existing tools ...
    GET_WEATHER = "get_weather"
    SEARCH_WEB = "search_web"
    GET_USER_ORDERS = "get_user_orders"
    NEW_TOOL_NAME = "new_tool_name"  # <--- 新增
```

### 1.2 使用装饰器注册实现

在同一文件 (`app/chat_service/core/llm_tools.py`) 或其他模块导入 `registry` 并使用 `@registry.register` 装饰器注册函数。

```python
# app/chat_service/core/llm_tools.py

from pydantic import BaseModel, Field

# 1. 定义参数 Schema
class NewToolArgs(BaseModel):
    query: str = Field(..., description="The search query")
    limit: int = Field(default=5, description="Max results")

# 2. 注册工具
@registry.register(
    name=FuncName.NEW_TOOL_NAME.value, 
    description="Description of what this tool does.", 
    args_schema=NewToolArgs
)
async def new_tool_implementation(query: str, limit: int = 5) -> str:
    # 实现业务逻辑
    return f"Search results for {query}: ..."
```

---

## 2. 配置新模型 (Configure New Model)

当接入新的模型提供商（如 Kimi, DeepSeek 等）或同一提供商的新模型时，需要涉及以下文件的修改：

### 2.1 添加配置字段

在 `app/chat_service/core/config.py` 的 `Settings` 类中添加对应的配置项。

```python
# app/chat_service/core/config.py

class Settings(BaseSettings):
    openai: LLMClientConfig
    gemini: LLMClientConfig
    qwen: LLMClientConfig
    
    # 新增 Kimi 配置
    kimi: LLMClientConfig  # <--- 新增
    
    model_config = SettingsConfigDict(env_nested_delimiter='__', env_file='.env', extra='ignore')
```

### 2.2 定义运行时配置 (Runtime Config)

在 `app/chat_service/core/schema.py` 中定义新的 `RuntimeConfig` 模型，并将其加入 `GenerationConfig` 联合类型。

```python
# app/chat_service/core/schema.py

# 1. 定义新的 RuntimeConfig
class KimiRuntimeConfig(BaseModel):
    provider: Literal["kimi"] = "kimi"
    # 使用 default_factory 从 settings 读取默认值
    model: str = Field(default_factory=lambda: settings.kimi.model)
    temperature: float = Field(default_factory=lambda: settings.kimi.temperature)
    max_tokens: int = Field(default_factory=lambda: settings.kimi.max_tokens)
    # ... 其他特定参数

# 2. 更新 GenerationConfig Union
GenerationConfig = Union[
    OpenAIRuntimeConfig, 
    GeminiRuntimeConfig, 
    QwenRuntimeConfig, 
    KimiRuntimeConfig  # <--- 新增
]
```

### 2.3 更新 Provider 校验

如果该模型使用 OpenAI 兼容协议（通常是），则需要在 `app/chat_service/core/llm_providers/openai_provider.py` 中允许该配置类型。

```python
# app/chat_service/core/llm_providers/openai_provider.py

from app.chat_service.core.schema import (
    # ...
    KimiRuntimeConfig  # <--- 导入
)

class OpenAICompatibleProvider(BaseLLMProvider):
    # ...
    
    async def stream_reply(self, config: GenerationConfig, payload: LLMPayload, ...):
        # ...
        
        # 1. 确保 config 类型正确
        if not isinstance(config, (OpenAIRuntimeConfig, QwenRuntimeConfig, KimiRuntimeConfig)): # <--- 添加判断
             raise ModelConfigError(f"Invalid config type: {type(config)}...")
             
        # ...
```

### 2.4 注册 Provider

最后，在 `app/core/lifespan.py` 或 `llm_client_manager` 初始化的地方注册该 Provider 实例。

```python
# app/core/lifespan.py

if hasattr(settings, 'kimi') and settings.kimi:
    llm_manager.register("kimi", OpenAICompatibleProvider(settings.kimi))
```
