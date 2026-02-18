# ChatService



```
# 文件夹结构

/chat_service
	/core
		/schema.py 							# DTO
		/exeptions.py 					# custom exceptions
		/llm_client_manager.py	# httpx async client + Async SDK Injection
														# add this to app/core/lifespan.py
	chat_service.py						# ChatService Enter File
	
	
```



## Task



### levle 1: LLM工具函数定义

```python
# chat_service/core/schema.py

from pydantic import BaseModel, Field
from typing import Callable, Type, Any
import json

# 1. 定义底层 Tool 结构
@dataclass
class LLMTool:
    name: str
    description: str
    args_schema: Type[BaseModel]
    func: Callable

 
```



```python
# chat_service/chat_service.py

class ChatService:
  def __init__(self):
    self.tools = registry.tools

  def _tool_to_llm_schema() -> dict:
   	# 把LLM 工具定义翻译成能读懂的格式
    return {
			"type": "function"
      "function": {
      	"name": tool.name
        "description": tool.description
        "parameters": tool.args_chema.model_json_schema()
    	}
    }
    
    
    async def run_tool(self, 
                       tool_name: str, 
                       args_json:str,
                      context_kwargs: dict = None # 用户数据，动态加载
                      ) ->str:
      # 执行LLM调用的工具
      	# 检查工具是否存在 （看注册列表）
        # 检验参数是否合格
        # 参数解包传给Func: case A: 原生异步; case B: 传统同步（asyncio.to_thread) 
        # 返回最终结果
      # 函数不存在、参数不正确，优先返回字符串，便于LLM进一步处理
```



```python

# chat_service/core/llm_tools.py

# 1. 先清晰地统一定义所有支持的工具名枚举
class FuncName(str, Enum):
    GET_WEATHER = "get_weather"
    SEARCH_WEB = "search_web"
    GET_USER_ORDERS = "get_user_orders"

# 2. 核心：工具注册中心
class ToolRegistry:
    def __init__(self):
        # 这是一个大字典，键是工具名，值是 LLMTool 对象
        self.tools: Dict[str, LLMTool] = {}

    def register(self, name: str, description: str, args_schema: Type[BaseModel]):
        """
        这就是那个神奇的装饰器工厂。
        它接收元数据，返回一个真正的装饰器函数。
        """
        def decorator(func: Callable):
            # 1. 组装工具对象
            tool = LLMTool(
                name=name,
                description=description,
                args_schema=args_schema,
                func=func
            )
            # 2. 存入字典（注册动作在这里完成）
            self.tools[name] = tool
            
            # 3. 原样返回函数，不改变函数原本的行为
            return func
            
        return decorator

# 3. 实例化一个全局单例
# 整个系统共享这一个 registry
registry = ToolRegistry()

# ==========================================
# 下面是你实际编写工具的地方(示例)
# ==========================================

# 工具 A：普通工具（所有参数都由 LLM 提供）
class GetWeatherArgs(BaseModel):
    location: str = Field(..., description="需要查询天气的城市")

@registry.register(
    name=FuncName.GET_WEATHER.value, 
    description="获取指定城市的天气", 
    args_schema=GetWeatherArgs
)
def get_weather_api(location: str) -> str:
    # 真实的业务逻辑
    return f"{location} 的天气是晴天，25度。"


# 工具 B：带上下文的工具（高级技巧）
# 注意：Schema 里绝对不能写 user_id！因为 LLM 不知道 user_id 是什么。
class GetUserOrdersArgs(BaseModel):
    time_range: str = Field(default="all", description="查询的时间范围，如 '30days', 'all'")

@registry.register(
    name=FuncName.GET_USER_ORDERS.value,
    description="查询当前用户的历史订单状态",
    args_schema=GetUserOrdersArgs
)
def get_user_orders_api(time_range: str, user_id: str) -> str:
    # 这里的 user_id 是由我们的系统动态注入的，time_range 是 LLM 传的
    # 真实的业务逻辑：去数据库查该用户的订单
    return f"用户 {user_id} 在 {time_range} 内有 2 笔已完成订单。"

```



### level 2: 组装发送给LLM的payload

Params: {chat_history, user_query, session_context, system_prompt}

```python
# chat_service/chat_service.py

class ChatService:
  
		def build_llm_payload(
      self,
      system_prompt: str,
      chat_history: ChatHistory, 
      user_query: UserQuery, 
      session_context: SessionContext, 
      allowed_tools： List[FuncName] 		# 用户权限下，可能用到的tools
      
    ) -> LLMPayload
    
    # 动态注入SOP偏好到System Prompt中
    
    # 组装标准的Message数组（加入system prompt, 历史会话, 用户的新问题)
    	# BaseModel 转为字典
    # 过滤出可用的 Tools
    
    # 返回 Payload
```



Result: {markdown_formatted_prompt}

**system_prompt**: 在一个单独的prompts/system_prompts/文件夹下进行管理，由sessionService决定传入哪一个systemprompt

```python
# chat_service/core/schema.py


# 假设的基础 ChatMessage
# ==========================================
# 💥 新增：LLM 交互载荷 (Payload) 的严谨 DTO
# ==========================================

class RoleType(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"

class ToolCallFunction(BaseModel):
    name: str
    arguments: str # 这里通常是 JSON 字符串

class ToolCall(BaseModel):
    id: str
    type: Literal["function"] = "function"
    function: ToolCallFunction

class LLMMessage(BaseModel):
    """单条聊天消息的标准结构"""
    role: RoleType
    content: Optional[str] = None
    
    # 当 role="assistant" 时，大模型可能会返回想要调用的工具列表
    tool_calls: Optional[List[ToolCall]] = None
    
    # 当 role="tool" 时，我们必须提供对应的工具执行结果和 ID
    tool_call_id: Optional[str] = None
    name: Optional[str] = None # 工具名称

class ChatHistory(BaseModel):
	chat_history: List[LLMMessage]
  
class LLMPayload(BaseModel):
    """
    发送给大模型的最终载荷。
    这个对象将由 Level 2 的 build_llm_payload 生成，并原封不动地传给 Level 4。
    """
    chat_history: ChatHistory
    
    # 工具的 JSON Schema 列表（Level 1 转换出来的格式）
    tools: Optional[List[Dict[str, Any]]] = None
    
    # 强制模型使用特定工具，或设为 'auto'，或设为 'none'
    tool_choice: Optional[Union[str, Dict[str, Any]]] = "auto"
    

  
class UserQuery(LLMMessage): # a LLMMessage with fixed user field as 'user'
	role: Literal['user'] = RoleType.USER 
  content: str
  

class SOPPreference(BaseModel):
  id: UUID
  user_id: UUID
  sessoin_ids: List[UUID]
  subject: str # 主题，这个偏好是关于什么领域的
  content: str # 具体的偏好内容
	keywords: List[str] # 一些关键词，用于索引
  
  
class SessionContext(BaseModel):
  user_sop_preferences: List[SOPPreference] 
```





###  level 3: 工厂函数，返回llm实例

记得在 llm client manager 刚启动的时候，先检测每个config 的配置是否满足



```
chat_service/core/
├── config.py                 # 配置文件
├── llm_client_manager.py     # 纯粹的调度器（不再包含任何具体 SDK 逻辑）
└── llm_providers/            # 💥 新增：客户端插件目录
    ├── __init__.py
    ├── base.py               # 定义接口标准
    ├── openai_provider.py    # OpenAI 兼容协议实现 (适用于 OpenAI, Qwen, DeepSeek...)
    └── gemini_provider.py    # Google 官方协议实现
```



```python
# app/chat_service/core/config.py


#    ==========  LLM Client Config ==========

class LLMClientConfig(BaseModel):
    limits_max_connections: int = Field(default=100)
    limits_keepalive: int = Field(default=20)
    timeout: float = Field(default=30.0)
    api_key: str = Field(..., description="必须配置 API KEY")
    base_url: str | None = Field(default=None, description="自定义的第三方 API 网关/代理地址")

class Settings(BaseSettings):
    # 自动从环境变量加载，例如 OPENAI_API_KEY=sk-... 就会自动注入
    openai: LLMClientConfig
    gemini: LLMClientConfig
    qwen: LLMClientConfig     # 👈 新增通义千问配置

    model_config = SettingsConfigDict(env_nested_delimiter='__', env_file='.env') # .env 与 app/ 在同一路径下

# 实例化全局配置
settings = Settings() 
# 💡 Fail Fast：如果环境变量里没配 OpenAI/Gemini 的 api_key，这行代码会直接抛出 ValidationError 阻止启动！
```

```python
# chat_service/core/llm_providers/base.py

from abc import ABC, abstractmethod
from typing import Any

class BaseLLMProvider(ABC):
    """所有 LLM 客户端的统一抽象基类"""
    
    @abstractmethod
    async def startup(self):
        """初始化连接池和 SDK"""
        pass

    @abstractmethod
    async def shutdown(self):
        """关闭连接池释放资源"""
        pass

 
      
     
    @abstractmethod
    def get_sdk(self) -> Any:
        """返回实例化后的官方 SDK"""
        pass
```

```python
# chat_service/core/llm_providers/openai_provider.py
import httpx
from openai import AsyncOpenAI
from chat_service.core.llm_providers.base import BaseLLMProvider
from chat_service.core.config import LLMClientConfig

class OpenAICompatibleProvider(BaseLLMProvider):
    def __init__(self, config: LLMClientConfig):
        # 接收外部传入的 config，实现配置与逻辑分离
        self.config = config
        self._http_client: httpx.AsyncClient | None = None
        self._sdk: AsyncOpenAI | None = None

    async def startup(self):
        self._http_client = httpx.AsyncClient(
            limits=httpx.Limits(
                max_connections=self.config.limits_max_connections,
                max_keepalive_connections=self.config.limits_keepalive
            ),
            timeout=httpx.Timeout(self.config.timeout)
        )
        
        kwargs = {
            "api_key": self.config.api_key,
            "http_client": self._http_client
        }
        if self.config.base_url:
            kwargs["base_url"] = self.config.base_url
            
        self._sdk = AsyncOpenAI(**kwargs)
        print(f"✅ OpenAI 兼容客户端启动成功 (Base URL: {self.config.base_url or '官方默认'})")

    async def shutdown(self):
        if self._http_client:
            await self._http_client.aclose()
            print("🛑 OpenAI 兼容客户端已关闭")

    def get_sdk(self) -> AsyncOpenAI:
        if not self._sdk:
            raise RuntimeError("SDK 尚未初始化")
        return self._sdk
      
 
```



```python
# chat_service/core/llm_providers/gemini_provider.py

# 相同逻辑
```



```python
# chat_service/core/llm_client_manager.py
from typing import Dict, Any
from chat_service.core.llm_providers.base import BaseLLMProvider

class LLMClientManager:
    def __init__(self):
        # 存放所有已注册的 provider
        self.providers: Dict[str, BaseLLMProvider] = {}

    def register(self, provider_name: str, provider: BaseLLMProvider):
        """注册一个新的 LLM 客户端"""
        self.providers[provider_name] = provider

    async def startup(self):
        """遍历并启动所有已注册的客户端"""
        for name, provider in self.providers.items():
            await provider.startup()
            
    async def shutdown(self):
        """遍历并关闭所有已注册的客户端"""
        for name, provider in self.providers.items():
            await provider.shutdown()

    def get_sdk(self, provider_name: str) -> Any:
        """根据名字获取对应的 SDK"""
        if provider_name not in self.providers:
            raise ValueError(f"未注册的 LLM 提供商: {provider_name}")
        return self.providers[provider_name].get_sdk()

# 全局单例
llm_manager = LLMClientManager()
```

```python
# app/core/lifespan.py
from contextlib import asynccontextmanager
from fastapi import FastAPI

from chat_service.core.config import settings
from chat_service.core.llm_client_manager import llm_manager
from chat_service.core.llm_providers.openai_provider import OpenAICompatibleProvider
# from chat_service.core.llm_providers.gemini_provider import GeminiProvider

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ================================
    # 1. 动态注册你需要的模型客户端
    # ================================
    
    # 注册原版 OpenAI
    llm_manager.register("openai", OpenAICompatibleProvider(settings.openai))
    
    # 💥 魔法时刻：使用兼容类直接注册 Qwen！完全复用代码！
    llm_manager.register("qwen", OpenAICompatibleProvider(settings.qwen))
    
    
    # 注册 Gemini (如果实现了的话)
    llm_manager.register("gemini", GeminiProvider(settings.gemini))

    # ================================
    # 2. 统一初始化
    # ================================
    print("🚀 正在初始化所有 LLM 客户端...")
    await llm_manager.startup()
    
    yield
    
    # ================================
    # 3. 统一销毁
    # ================================
    print("📉 正在销毁所有 LLM 客户端...")
    await llm_manager.shutdown()
```







1. 实现LLM Manager，httpx 连接池，注入官方SDK
2. SDK 的`api_key` 配置在`chat_service/core/config,py`
3. 把 llm manager 注册在全局FastAPI `app/core/lifespan.py`





### level 4: 流式返回

```python
# chat_service/core/schema.py 


# ==========================================
# 1. 流式响应协议 (Server-Sent Events DTO)
# ==========================================

class StreamEventType(str, Enum):
    # 修正：Enum 的定义需要用 =
    MESSAGE_CHUNK = "message_chunk"     # 普通文本片段
    TOOL_CALL_CHUNK = "tool_call_chunk" # 💡 新增：告诉前端"我正在打算调工具"
    STATS = "statistic"                 # 结束时的统计信息
    ERROR = "error"

class BaseStreamReply(BaseModel):
    event_type: StreamEventType
    seq_id: int = Field(..., description="自增序列号，前端用于排序去重")

class MessageChunkEvent(BaseStreamReply):
    event_type: Literal[StreamEventType.MESSAGE_CHUNK] = StreamEventType.MESSAGE_CHUNK
    content: str # 当前片段的文本

class ToolCallChunkEvent(BaseStreamReply):
    """当 LLM 决定调用工具时，流式返回工具名和参数片段"""
    event_type: Literal[StreamEventType.TOOL_CALL_CHUNK] = StreamEventType.TOOL_CALL_CHUNK
    tool_name: Optional[str] = None
    args_chunk: str # 参数的 JSON 片段，前端可以展示 "正在解析参数..."

class StatisticEvent(BaseStreamReply):
    event_type: Literal[StreamEventType.STATS] = StreamEventType.STATS
    input_tokens: int
    output_tokens: int
    response_duration: float

# 定义一个联合类型，方便类型提示
StreamReply = Union[MessageChunkEvent, ToolCallChunkEvent, StatisticEvent]


# ==========================================
# 2. LLM 运行时参数 (Discriminated Union)
# ==========================================

class OpenAIRuntimeConfig(BaseModel):
    provider: Literal["openai"] = "openai" # 👈 判别字段
    model: str = "gpt-4-turbo"
    temperature: float = 0.7
    max_tokens: int = 2048
    # OpenAI 专属参数
    frequency_penalty: float = 0.0

class GeminiRuntimeConfig(BaseModel):
    provider: Literal["google"] = "google" # 👈 判别字段
    model: str = "gemini-1.5-pro"
    temperature: float = 0.5
    # Gemini 专属参数
    top_k: int = 40 
    max_output_tokens: int = 8192

# 💥 核心答案：使用 Union
# Pydantic 会根据传入字典里的 "provider" 字段，自动决定用哪个类去校验
GenerationConfig = Union[OpenAIRuntimeConfig, GeminiRuntimeConfig]
```


```python
# chat_service/core/llm_providers/base.py

class BaseLLMProvider(ABC):
    # 💥 新增： 强制每个接入的 Provider 必须自己实现数据流翻译逻辑
    @abstractmethod
    async def stream_reply(
        self, config: GenerationConfig, payload: LLMPayload
    ) -> AsyncGenerator[StreamReply, None]:
        """
        接收标准参数，返回标准事件流。
        具体怎么和第三方 SDK 交互，怎么拆解流，由各个子类自己决定！
        """
        pass

```

```python
# chat_service/core/llm_providers/openai_provider.py

class OpenAICompatibleProvider(BaseLLMProvider):
  
     # 💥 实现流式接口
    async def stream_reply(
        self, 
      config: GenerationConfig, 
      payload: LLMPayload
    ) -> AsyncGenerator[StreamReply, None]:
        
        start_time = time.time()
        seq_id = 0
        output_tokens = 0
        
        # 1. 剥离并转换 Payload 为字典，丢弃为 None 的字段
    
    
        
        # 2. 组装请求参数 (此时我们确信 config 已经是 OpenAIRuntimeConfig)
        
        

        # 3. 发起原生 SDK 请求
        
        
        
        # 4. 翻译网络流 
        
        
        
            
            # 普通文本
            
            
            # 工具调用碎片
            
            
        # 5. 结束统计
       
     
```

```python
# chat_service/core/llm_providers/gemini_provider.py

# 相同逻辑
```
```python
# chat_service/core/llm_client_manager.py

class LLMClientManager:
    # ... (保留之前的逻辑) ...

    # 新增一个方法，不再只返回底层的 sdk，而是返回整个 Provider 插件
    def get_provider(self, provider_name: str) -> BaseLLMProvider:
        if provider_name not in self.providers:
            raise ValueError(f"未注册的 LLM 提供商: {provider_name}")
        return self.providers[provider_name]

llm_manager = LLMClientManager()
```
```python
# chat_service/chat_service.py
from typing import AsyncGenerator
from chat_service.core.schema import GenerationConfig, LLMPayload, StreamReply
from chat_service.core.llm_client_manager import llm_manager

class ChatService:
    # ... 省略其他方法 ...

    async def stream_reply(
        self, 
        runtime_config: GenerationConfig, 
        payload: LLMPayload
    ) -> AsyncGenerator[StreamReply, None]:
        """
        极其纯净的代理层。根据请求的提供商，直接将任务分发给对应的 Provider 插件。
        """
        
        # 1. 从注册中心获取对应的业务处理插件（比如 OpenAICompatibleProvider）
        provider = llm_manager.get_provider(runtime_config.provider)
        
        # 2. 调用插件的 stream_reply 方法，原样透传给上层
        async for event in provider.stream_reply(config=runtime_config, payload=payload):
            # 这里你可以做一些通用的中间件操作，比如打印日志、做安全拦截等
            yield event
```

### level 5: 整合LLM：组装prompt，拿实例，执行工具，流式返回

```python
# chat_service/core/schema.py

class StreamEventType(str, Enum):
    MESSAGE_CHUNK = "message_chunk"
    TOOL_CALL_CHUNK = "tool_call_chunk"
    STATS = "statistic"
    ERROR = "error"
    # 💥 1. 新增：状态/步骤流转事件
    STATUS = "status" 

# ... (保留你之前的 BaseStreamReply 等定义) ...

# 💥 2. 新增对应的 DTO
class StatusEvent(BaseStreamReply):
    """用于告诉前端当前 Agent 正在干什么（思考、调工具等）"""
    event_type: Literal[StreamEventType.STATUS] = StreamEventType.STATUS
    message: str          # 给用户看的友好文案，例如："正在查询北京天气..."
    tool_name: Optional[str] = None # 附加信息：当前正在调用的工具名（前端可用于展示不同的 Icon）
    status: Literal["running", "success", "failed"] = "running" # 步骤状态

# 💥 3. 别忘了把它加进 Union 里！
StreamReply = Union[
    MessageChunkEvent, 
    ToolCallChunkEvent, 
    StatisticEvent, 
    StatusEvent  # <-- 加在这里
]
```







```python
# chat_service/chat_service.py

class ChatService:
    def __init__(self):
        self.tools = registry.tools
        
    # ... (保留之前的 run_tool, build_llm_payload, stream_reply 等方法) ...

    async def chat_stream_with_tools(
        self, runtime_config: GenerationConfig, payload: LLMPayload, context_kwargs: dict = None, max_loops: int = 5
    ) -> AsyncGenerator[StreamReply, None]:
        """Level 5: Agentic Loop (核心状态机)"""
        if context_kwargs is None: context_kwargs = {}
        current_payload = payload
        loop_count = 0
        global_seq_id = int(time.time() * 1000)
        provider = llm_manager.get_provider(runtime_config.provider)

        while loop_count < max_loops:
            loop_count += 1
            tool_calls_acc = {}

            if loop_count > 1:
                global_seq_id += 1
                yield StatusEvent(seq_id=global_seq_id, message="正在思考总结...", status="running")

            # 接收插件吐出的标准事件流
            async for event in provider.stream_reply(runtime_config, current_payload):
                global_seq_id += 1
                event.seq_id = global_seq_id
                yield event

                if isinstance(event, ToolCallChunkEvent):
                    idx = event.index
                    if idx not in tool_calls_acc:
                        tool_calls_acc[idx] = {"id": f"call_{idx}", "name": event.tool_name or "", "arguments": event.args_chunk or ""}
                    else:
                        if event.tool_name: tool_calls_acc[idx]["name"] += event.tool_name
                        if event.args_chunk: tool_calls_acc[idx]["arguments"] += event.args_chunk

            if not tool_calls_acc: break

            # 执行工具
            assistant_tool_msg = LLMMessage(role=RoleType.ASSISTANT, tool_calls=[])
            tool_results_msgs = []

            for idx, data in tool_calls_acc.items():
                t_name = data["name"]
                t_args = data["arguments"]
                
                assistant_tool_msg.tool_calls.append(ToolCall(id=data["id"], function=ToolCallFunction(name=t_name, arguments=t_args)))
                
                desc = self.tools[t_name].description if t_name in self.tools else t_name
                global_seq_id += 1
                yield StatusEvent(seq_id=global_seq_id, message=f"正在 {desc}...", tool_name=t_name, status="running")
                
                res_str = await self.run_tool(t_name, t_args, context_kwargs)
                
                global_seq_id += 1
                yield StatusEvent(seq_id=global_seq_id, message=f"已完成 {desc}", tool_name=t_name, status="success")
                
                tool_results_msgs.append(LLMMessage(role=RoleType.TOOL, tool_call_id=data["id"], name=t_name, content=res_str))

            current_payload.messages.append(assistant_tool_msg)
            current_payload.messages.extend(tool_results_msgs)
            
        else:
            yield MessageChunkEvent(seq_id=99999, content="\n\n[系统] 操作超限，已强制停止。")
```

