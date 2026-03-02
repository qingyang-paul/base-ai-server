# Subscription Service

## 1. 模块概述

Subscription Service 服务致力于解决系统平台中核心的**计费、额度与套餐管理**。模块的核心职责包括：

1. **统一模型计费标准管理**：作为全系统的 Single Source of Truth，定义所有 LLM 的基础计费费率（Prompt / Completion 比例）、上下文阈值等。
2. **商业化套餐组配置**：维护系统所提供的订阅计划（如 Free, Pro），定义每个订阅计划拥有的基础额度、允许访问的模型列表、可用工具列表以及计费折扣。
3. **用户资产与订阅状态管理**：处理用户维度的订阅初始化、额度扣减与状态跟踪。

---

## 2. 开放与集成的接口

该服务的大多功能作为内部服务支撑其他模块，目前强依赖并开放以下集成点：

### 2.1 用户注册集成 (Auth Service)

**端点**: `POST /api/v1/auth/verify-email`
当新用户完成邮箱验证并成功注册时，Auth Service 会通过由于发出的 `init_user_subscription_task` 异步任务触发 Subscription Service 的流转。此过程会自动为该用户初始化默认的免费套餐（如 `Free Plan`）并注入初始额度。

### 2.2 聊天与消费集成 (Chat Service)

在每次有效触发的大模型请求结束后，需要调用对应扣费服务（如 `SubscriptionService.process_message_billing()`）来进行额度扣减计算。此计算完全依赖于本模块中统一定义的对应大模型的输入输出费率以及用户当前挂载套餐的 `global_discount`（全局折扣）。

---

## 3. 后续拓展与配置指南

如果在未来需要添加新的模型、更改计费费率、或者新增商业化订阅套餐，您需要修改下面核心配置文件：

**核心配置文件**: `app/subscription_service/core/config.py`

*(注意：此模块的全局配置项直接以硬编码字典配置在文件中，并未通过 `BaseSettings` 读取 `.env` 环境变量)*

### 3.1 增加新的大模型 (模型计费与全局设定)

在 `MODEL_REGISTRY` 字典中新增模型定义。这是系统的“唯一事实来源”。

```python
# app/subscription_service/core/config.py
MODEL_REGISTRY: Dict[str, GlobalLLMConfig] = {
    # 现有模型...
    "deepseek-coder-v2": GlobalLLMConfig(
        model_id="deepseek-coder-v2", 
        provider="deepseek", 
        base_prompt_ratio=0.005,      # 输入费率
        base_completion_ratio=0.015,  # 输出费率
        max_tokens_per_request=4096,
        temperature=1.0
    )
}
```

**关键点**: `provider` 字段统一使用机构名（如 `gemini` 而不是 `google`），这关联到全局的字段转换。

### 3.2 新增或修改订阅套餐 (商业化逻辑)

在 `PLAN_REGISTRY` 字典中新增或调整套餐。套餐中不需要再次定义模型费率，只需要引用 `MODEL_REGISTRY` 中的 `model_id`。

```python
# app/subscription_service/core/config.py
PLAN_REGISTRY: Dict[str, PlanConfig] = {
    # 现有套餐...
    "enterprise": PlanConfig(
        name="Enterprise Plan",
        base_credits=50000, # 每个周期配额
        default_model="gpt-4-turbo",
        # 控制该套餐能访问的模型列表 (通过 model_id 关联)
        allowed_models=["gpt-4-turbo", "gemini-3.1-pro-preview", "deepseek-coder-v2"],
        global_discount=0.8, # 可以为企业版提供八折计算的统一下浮
        allowed_tools=[FuncName.SEARCH_WEB] # 绑定高级专属工具
    )
}
```

### 3.3 工具控制注意事项

当你在套餐里配置了 `allowed_tools` 之后，需要确保对应的工具名类型已经在 `app/chat_service/core/llm_tools.py` 的枚举中被定义，并在 Chat Service 中被安全注册和挂载使用（详情参阅 `chat_service/README.md`）。

---

## 4. 开发与部署注意事项

1. **数据库外键未完善**：当前版本 `core/model.py` 中的数据库模型可能存在外键约束缺失或待补充的情况，在拓展数据层（如订阅历史、独立流水表）时需自行补充对应用的外键结构。
2. **Taskiq 生命周期注册顺序**：服务强依赖于异步后台任务（例如自动刷新或初始化额度）。在 `app/core/lifespan.py` 中，**必须确保** `taskiq` 的任务对象在注册时，严格先于 broker 的启动完成挂载，否则将在启动时抛出找不到该后台任务的致命异常。
