# Subscription Service

## 1. Module Overview

The Subscription Service is dedicated to solving the core **billing, quota, and plan management** in the system platform. The module's core responsibilities include:

1. **Unified Model Billing Standard Management**: As the Single Source of Truth for the entire system, it defines the base billing rates (Prompt / Completion ratio), context thresholds, etc., for all LLMs.
2. **Commercial Plan Group Configuration**: Maintains the subscription plans provided by the system (like Free, Pro), defining the basic quotas each subscription plan has, the list of allowed models to access, the list of available tools, and billing discounts.
3. **User Assets and Subscription Status Management**: Handles subscription initialization, quota deduction, and status tracking at the user dimension.

---

## 2. Exposed and Integrated Interfaces

Most functions of this service act as internal services supporting other modules. Currently, it strongly depends on and exposes the following integration points:

### 2.1 User Registration Integration (Auth Service)

**Endpoint**: `POST /api/v1/auth/verify-email`
When a new user completes email verification and successfully registers, the Auth Service will trigger the flow of the Subscription Service via the dispatched `init_user_subscription_task` asynchronous task. This process will automatically initialize a default free plan (like `Free Plan`) for the user and inject the initial quota.

### 2.2 Chat and Consumption Integration (Chat Service)

After every validly triggered LLM request ends, the corresponding billing deduction service (like `SubscriptionService.process_message_billing()`) needs to be called to calculate the quota deduction. This calculation relies entirely on the identically defined input/output rates of the corresponding LLM in this module, as well as the `global_discount` of the user's currently mounted plan.

---

## 3. Future Extension and Configuration Guide

If you need to add new models, change billing rates, or add new commercial subscription plans in the future, you need to modify the following core configuration file:

**Core Configuration File**: `app/subscription_service/core/config.py`

*(Note: The global configuration items of this module are directly hardcoded as dictionary configurations in the file, and are not read from the `.env` environment variables via `BaseSettings`)*

### 3.1 Adding a New LLM (Model Billing and Global Settings)

Add the model definition in the `MODEL_REGISTRY` dictionary. This is the system's "single source of truth".

```python
# app/subscription_service/core/config.py
MODEL_REGISTRY: Dict[str, GlobalLLMConfig] = {
    # Existing models...
    "deepseek-coder-v2": GlobalLLMConfig(
        model_id="deepseek-coder-v2", 
        provider="deepseek", 
        base_prompt_ratio=0.005,      # Input rate
        base_completion_ratio=0.015,  # Output rate
        max_tokens_per_request=4096,
        temperature=1.0
    )
}
```

**Key Point**: The `provider` field uniformly uses the organization name (e.g., `gemini` instead of `google`), which relates to global field conversion.

### 3.2 Adding or Modifying Subscription Plans (Commercial Logic)

Add or adjust plans in the `PLAN_REGISTRY` dictionary. You do not need to define model rates in the plan again; just reference the `model_id` in the `MODEL_REGISTRY`.

```python
# app/subscription_service/core/config.py
PLAN_REGISTRY: Dict[str, PlanConfig] = {
    # Existing plans...
    "enterprise": PlanConfig(
        name="Enterprise Plan",
        base_credits=50000, # Quota per period
        default_model="gpt-4-turbo",
        # Controls the list of models this plan can access (associated via model_id)
        allowed_models=["gpt-4-turbo", "gemini-3.1-pro-preview", "deepseek-coder-v2"],
        global_discount=0.8, # Can provide a unified 20% off calculation for the enterprise version
        allowed_tools=[FuncName.SEARCH_WEB] # Bind advanced exclusive tools
    )
}
```

### 3.3 Tool Control Considerations

When you configure `allowed_tools` in a plan, you need to ensure that the corresponding tool name type has already been defined in the enumeration of `app/chat_service/core/llm_tools.py`, and is safely registered and mounted for use in Chat Service (for details, see `chat_service/README.md`).

---

## 4. Development and Deployment Considerations

1. **Database Foreign Keys Incomplete**: The database models in the current version of `core/model.py` might have missing or to-be-supplemented foreign key constraints. When expanding the data layer (like subscription history, independent ledger tables), you need to supplement the applied foreign key structures yourself.
2. **Taskiq Lifecycle Registration Order**: The service strongly relies on asynchronous background tasks (such as auto-refreshing or initializing quotas). In `app/core/lifespan.py`, you **must ensure** that the `taskiq` task objects are registered strictly before the broker startup finishes mounting, otherwise a fatal exception of not finding the background task will be thrown during startup.
