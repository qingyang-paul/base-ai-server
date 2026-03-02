# Base AI Server

Base AI Server 是一个功能完备、高度模块化的通用人工智能后台服务端框架。项目通过 FastAPI 提供高性能的异步 HTTP 接口，并深度集成了 PostgreSQL、Redis、Taskiq 异步任务队列以及完善的 OpenTelemetry 可观测性链路。

## 1. 底层核心架构 (Core Infrastructure)

系统的底层设施封装在 `app/core/` 目录下，负责承载全局性的非业务基础能力：

- **全局配置加载 (`app/core/config.py`)**：使用 Pydantic `BaseSettings` 集中化管理环境变量，包括工作环境、Redis/PG 数据库连接串、SMTP 邮箱、Telemetry 配置等，并作为全局唯一的配置来源。
- **可观测与链路追踪 (`app/core/telemetry.py`)**：集成 OpenTelemetry (OTel)，配置 OTLP gRPC 导出器，并通过 `FastAPIInstrumentor` 自动为每个 FastAPI HTTP 请求插桩生成 Span 和 Trace ID。
- **结构化日志 (`app/core/logger.py`)**：深度定制了 Loguru，可根据环境开关一键切换到 JSON 格式输出。同时它劫持了标准库和 Uvicorn 的日志，并通过 Patcher 自动把当前上下文中 OpenTelemetry 的 `trace_id` 抽取出来写入到每一条日志中，实现完美的“日志-链路追踪”绑定。
- **后台异步任务中间件 (`app/core/taskiq_middleware.py`)**：使用 Taskiq 处理后台耗时任务。自建了 `OpentelemetryMiddleware` 中间件，能在触发异步任务时自动序列化注入当前的 Trace 上下文，确保跨进程派发的后台任务依然和主请求保持同一条链路。
- **依赖注入中枢 (`app/dependencies.py`)**：FastAPI 的核心依赖注入点（IoC），自动按需分配从全局应用状态 (`app.state`) 中拉取的数据库连接池 (SQLAlchemy Session) 和 Redis 客户端，进而向下实例化所需的各路 Service 以及 Repo 实例，保证请求隔离。
- **服务生命周期管控 (`app/core/lifespan.py`)**：集中接管系统启动与停止逻辑。一次性建立各种异步连接池、挂载日志系统、实例化限流器并初始化下沉的所有 LLM 客户端与本地 Prompt 资产，完成优雅启停。

---

## 2. 核心业务领域 (Domain Services)

本项目按照领域驱动设计 (DDD) 拆分了多个专注的微服务模块，它们松耦合地协同工作。各个模块的详细功能与配置指南，请查阅各自独立的说明书：

1. **[Auth Service (身份认证服务)](./app/auth_service/README.md)**  
   提供涵盖注册、验证、登录、JWT 双 Token 签发与刷新、密码重置的完整鉴权闭环，同时提供全局请求限流 (Rate Limiter) 标准。
2. **[Chat Service (大模型交互引擎)](./app/chat_service/README.md)**  
   统管 OpenAI、Gemini、Qwen 等多元异构大语言模型客户端的连接池，封装流式事件通讯协议，并提供了本地智能函数调用 (Function Calling Tool) 的注册能力。
3. **[Subscription Service (计费与套餐管理)](./app/subscription_service/README.md)**  
   充当系统商业逻辑唯一真实来源 (Single Source of Truth)，统一界定各类 LLM 的基础计费率与不同商业套餐 (Free, Pro 等) 的配额、折扣与访问权限。
4. **[Session Service (会话与人设管家)](./app/session_service/README.md)**  
   负责承上启下连接业务，接管用户的聊天记忆(History)。采用 Redis+双写 Buffer 落库大幅优化数据库 I/O 延迟。内部还集成了基于 YAML Markdown 的系统预设 Prompt 动态加载体系。

---

## 3. 项目数据流转概览 (Data Flow)

一个典型的高级互动请求（比如用户向流式 AI 大模型提问）的数据流向如下：

1. **【请求接收与链路标记】**  
   HTTP 请求进入 FastAPI，`TelemetryMiddleware` 立刻生成 Trace Root，并将此 `trace_id` 下行绑定到本次请求的所有 Log 产生中。
2. **【身份校验与限流防护】**  
   中间件与 `dependencies.py` 读取 Token，通过 `Auth Service` 解析得到 `user_id`。如果超过接口访问频率限制，将被 `limiter.py` 拦截。
3. **【环境装配】**  
   FastAPI 通过依赖注入动态组装得到包含正确 DB/Redis Session 的 `SessionService`。
4. **【上下文本地重构】**  
   `SessionService` 根据 `session_id` 尝试从 Redis 读取用户的历史记录；如果未命中则带锁通过 PG 数据库装载。
5. **【商业权限裁定】**  
   `SessionService` 去 `SubscriptionService` 查询当前用户的商业套餐，获得允许请求的模型类型、折扣参数以及可用 Tools 白名单。
6. **【AI 对话与引擎分发】**  
   装配完整的 Payload 被转交给 `ChatService`。`ChatService` 中的 Provider 取用连接池请求对应的第三方大模型接口（并中途拦截可能的 Function Call 回调）。
7. **【流式返回与异步缓冲区落库】**  
   引擎向外抛出流式二进制块返回给客户端（保证极低延迟）。在整段流传输完毕后，后台才会被 `SessionService` 执行双写进入 Redis Buffer。如果 Buffer 满了，则会投递一条 `persist_session_buffer_task` 给 Taskiq 去执行数据库落盘。

---

## 4. 可拓展性分析 (Extensibility)

本脚手架的拓展性具有如下优势：

- **新增外部模型**：仅需在 `ChatService` 中扩充新的 Provider 子类并注册配置，然后在 `SubscriptionService` 的 `MODEL_REGISTRY` 标出单价即可插拔使用。
- **后台异步生态极好扩展**：Taskiq 原生支持 RabbitMQ 或 Redis 作为 Broker。若新增发邮件或定期账单清理等耗时工单，直接使用 `@broker.task` 装饰器编写代码，调用 `.kiq()` 即享非阻塞分布执行且追踪日志不断连的特性。
- **自定义人设热更新**：想创建特定领域的“智能分析专属 Agent”，只需要去 `SessionService` 的对应文件夹中增加 Markdown 文件，填写特定场景属性。下次进程随启即用。
