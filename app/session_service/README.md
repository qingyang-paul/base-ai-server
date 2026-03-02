# Session Service

## 1. 模块概述

Session Service 处于应用层的核心，负责串联前端用户的会话上下文（Session Context）、底层的 LLM 会话（Chat Service）以及用户的计费/权限系统（Subscription Service）。具体来说，它主要负责以下三大块：

1. **会话状体与历史管理 (Session & Context Management)**
   - 接管所有用户的 Chat Session，负责 Session Meta 信息的创建和更新。
   - 管理长下文的存储与读取。为了保证高性能流式响应，采用 **Redis 缓存 + Buffer 机制** 结合底层 PostgreSQL 进行持久化。
2. **系统提示词动态管理 (System Prompt Registry)**
   - 提供热加载、甚至内存级 O(1) 读取的 Prompt 管理系统。通过 `yaml` frontmatter 标注的 Markdown 文件进行系统人设和版本的无缝管理。
3. **请求组装与权限校验 (Payload Builder & Permission Check)**
   - 每次接收到用户发问，Session Service 负责查询 Subscription Service 获取当前用户所属的订阅套餐。
   - 根据套餐配置的可用模型列表和可用工具（Tools），校验并构建最终发送给 Chat Service 的 `GenerationConfig` 和 `LLMPayload`。

---

## 2. 核心机制解析

### 2.1 Prompt 注册与加载机制 (`prompt_registry.py`)

所有的 System Prompt 都以 `.md` 形式集中存放在 `app/session_service/core/system_prompts` 目录下。

- **文件规范**: 文件顶部必须包含 YAML Frontmatter 描述 `scene`（场景，如 `pal`）、`version`（如 `v1.0`）、以及 `description`。
- **内存驻留**: App 启动时通过 `initialize()` 单例加载读取所有文件内容驻入内存，避免运行时的磁盘 I/O。当服务更新 Prompt 时，只需新增 Markdown 文件，在代码重载后系统会通过版本对比 (`get_latest_prompt`) 自动采纳新的人设。

### 2.2 Redis 缓存与双写 Buffer 机制

为了对抗数据库 I/O 带来的延迟瓶颈，维持极致的 TTS (Time To First Token) 响应，Session Service 实现了智能的双写缓冲策略：

- **读缓存**: 会话记录优先从 `session_cache:{session_id}` 阅读，命中缺失时触发分布式锁 (`lock:session:{session_id}`) 从 Postgres 按需装载。
- **写缓冲 (`SESSION_BUFFER_THRESHOLD`)**: 生成的消息不立刻写入 Postgres。转而先写入 Redis Buffer 队列。只有当 Buffer 积压消息条数超过 `config.py` 中的 `SESSION_BUFFER_THRESHOLD` (默认 50) 时，才会派发 `persist_session_buffer_task` 异步 Taskiq 任务进行批量落库 (Persist to DB)。

---

## 3. 拓展与配置指南

当您需要为 Chat 模块进行二次开发或增加新特性时，大概率需要碰触以下配置点：

### 3.1 增加新的数字人设/新 Prompt 场景

1. **定义场景枚举**: 在 `app/session_service/core/prompt_registry.py` 的 `SystemPromptScene` 中加入新的枚举 (例如 `DATA_ANALYST = "data_analyst"`)。
2. **创建 Prompt 文件**: 在 `app/session_service/core/system_prompts/` 文件夹下新增 `.md`，写好 Frontmatter，例如：

   ```yaml
   ---
   scene: data_analyst
   version: v1.0
   description: 针对数据分析特化的提示词
   ---
   You are an expert Data Analyst. ...
   ```

   下次服务启动时，该 Prompt 会被作为 `DATA_ANALYST` 场景的最新版本接管使用。

### 3.2 调整会话参数阈值

在 `app/session_service/core/config.py` 中可以修改针对性能进行压栈的配置：

- `SESSION_INACTIVE_THRESHOLD`: (默认 300s) 会话多久不活跃后被视为过期或需要清理。
- `SESSION_BUFFER_THRESHOLD`: (默认 50条) 控制内存中堆砌多少条记录后才派发批量持久化的 Taskiq 任务，适当调高可以减少数据库事务数量。

### 3.3 工具/上下文关联透传

当前的代码预留了 `context_kwargs = {"user_id": str(user_id)}` 在 `handle_agent_stream_reply` 中注入给底层的工具链。如果您新开发的 Function Tool 需要用户的地理位置、语言偏好等，请在 `SessionService` 拿到请求后，直接把参数塞入该字典向后透传。
