# Chat Service Module (聊天服务模块)

该模块负责 AI 聊天服务的核心处理逻辑，囊括了与各大 LLM 提供商 (如 OpenAI, Gemini, Qwen) 的交互、本地工具 (Function Calling) 的调用、连接池管理以及流式响应的处理。

---

## 1. 模块的配置方式 (Configuration)

该模块的核心配置位于 `app/chat_service/core/config.py`，主要依赖基于 Pydantic 的 `Settings` 模型。系统的 LLM 行为及各项限制（如模型参数）会部分或全部委托给统一配置模块。

### 1.1 环境变量注入

所有的客户端配置 (`LLMClientConfig`) 会通过 Pydantic Settings 自动从环境 (`.env`) 中提取。
由于启用了嵌套分隔符 (`env_nested_delimiter='__'`)，在配置时应使用**双下划线**：

- `OPENAI__API_KEY=sk-xxxx`
- `GEMINI__API_KEY=AIzaSy...`
- `QWEN__BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1`

### 1.2 修改配置的注意事项

- **配置优先级与管理**：确保所有敏感数据 (API Key) 一定只能通过环境变量输入，**严禁硬编码**，否则会被忽略。
- **第三方代理配置**：如果需要统一走国内的第三方 API 网关，只需要配置对应的 `[PROVIDER]__BASE_URL` 字段即可。
- **全局参数分离**：与具体的连接配置(限流、超时)不同，LLM 请求中的具体生成参数 (如同一个请求用什么具体的 `model名称` , `temperature`等) 会通过全局范围的 `GlobalLLMConfig` 提供。在配置客户端层面时关注的是“如何连通”而并非“用什么系统 prompt 发言”。

---

## 2. 如何注册 LLM 客户端 (Register LLM Client)

客户端的生命周期（注册、启动、关闭）由 `app/chat_service/core/llm_client_manager.py` 下的全局单例 `llm_manager` 管理。

### 2.1 注册步骤

1. **实现 Provider**：继承并实现 `BaseLLMProvider` 抽象类（例如 `OpenAIProvider`, `GeminiProvider`），需自行管理底层异步客户端 (Async Client) 实例并在 `startup()` 和 `shutdown()` 里实现相关逻辑。
2. **注册到管理器**：在应用生命周期加载期间 (如 `lifespan.py`) 需要调用 `register` 挂载实例：

   ```python
   from app.chat_service.core.llm_client_manager import llm_manager
   from app.chat_service.core.config import settings
   
   # 实例化你的 Provider (需要传递设置)
   my_provider = MyNewAPIProvider(config=settings.my_new_llm)
   
   # 注册
   llm_manager.register("my_new_llm", my_provider)
   ```

3. **获取客户端调用**：随后在具体业务路由中，可通过 `llm_manager.get_sdk("my_new_llm")` 获取底层的具体异步客户端用于发请求，或直接调用 `llm_manager.get_provider(...)` 使用 Provider 的标准化接口封装。
4. **生命周期自动管理**：当程序启动和停止时，自动遍历并调用已经注册好的提供商的 `.startup()` 与 `.shutdown()` 方法。

---

## 3. 如何注册本地工具 (Register Tools)

该模块支持标准的 Function Calling 工具挂载，由 `app/chat_service/core/llm_tools.py` 的全局登记册 (`registry`) 统一收口与分发。

### 3.1 注册步骤

1. **注册唯一枚举**：首先必须向 `FuncName` 枚举追加新工具标识。

   ```python
   class FuncName(str, Enum):
       # ...
       NEW_FEATURE_TOOL = "new_feature_tool"
   ```

2. **定义 Pydantic 入参 Schema**：向 LLM 清晰表达该工具如果被调用，需要输出什么格式的 JSON 参数。

   ```python
   from pydantic import BaseModel, Field
   class NewFeatureArgs(BaseModel):
       query: str = Field(..., description="用户搜索的查询语句")
   ```

3. **使用 `@registry.register` 标记实现函数**：将需要给 AI 提供的方法挂载，使其可寻址。

   ```python
   from app.chat_service.core.llm_tools import registry, FuncName
   
   @registry.register(
       name=FuncName.NEW_FEATURE_TOOL.value,
       description="当用户询问XX信息时，使用此工具进行数据查找。",
       args_schema=NewFeatureArgs
   )
   async def handle_new_feature(query: str):
       # 具体后台业务逻辑
       return {"status": "success", "result": f"Answer for {query}"}
   ```

注册完毕后，在发送给 LLM 支持函数的 Prompt 时，可以自动通过 `registry.get_tool(...)` 序列化提取其 schema 发过去，在 LLM 选择调用工具时系统反向执行所挂载的 async function。
