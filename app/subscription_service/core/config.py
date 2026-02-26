from pydantic import BaseModel, Field
from typing import Literal, Dict, List, Optional
from app.chat_service.core.llm_tools import FuncName

# ==========================================
# 1. 全局模型注册表 (Single Source of Truth)
# ==========================================
class GlobalLLMConfig(BaseModel):
    model_id: str
    provider: Literal['openai', 'anthropic', 'gemini', 'qwen'] 
    base_prompt_ratio: float = Field(..., description="基准输入费率")
    base_completion_ratio: float = Field(..., description="基准输出费率")
    max_tokens_per_request: int = Field(default=4096)
    temperature: float = Field(default=1.0)

# 物理模型只在这里定义一次
MODEL_REGISTRY: Dict[str, GlobalLLMConfig] = {
    "gpt-4-turbo": GlobalLLMConfig(
        model_id="gpt-4-turbo", provider="openai",
        base_prompt_ratio=0.01, base_completion_ratio=0.03, max_tokens_per_request=8192,
        temperature=1.0
    ),
    "gemini-3-flash-preview": GlobalLLMConfig(
        model_id="gemini-3-flash-preview", provider="gemini",
        base_prompt_ratio=0.015, base_completion_ratio=0.075, max_tokens_per_request=8192,
        temperature=1.0
    ),
    "gemini-3-pro-preview": GlobalLLMConfig(
        model_id="gemini-3-pro-preview", provider="gemini",
        base_prompt_ratio=0.015, base_completion_ratio=0.075, max_tokens_per_request=8192,
        temperature=1.0
    ),
    "gemini-3.1-pro-preview": GlobalLLMConfig(
        model_id="gemini-3.1-pro-preview", provider="gemini",
        base_prompt_ratio=0.015, base_completion_ratio=0.075, max_tokens_per_request=8192,
        temperature=1.0
    ),
    "qwen": GlobalLLMConfig(
        model_id="Qwen3-VL-235B-A22B-Instruct", provider="qwen",
        base_prompt_ratio=0.01, base_completion_ratio=0.03, max_tokens_per_request=8192,
        temperature=1.0
    )
}

# ==========================================
# 2. 套餐与权限配置 (Business Logic)
# ==========================================
class PlanConfig(BaseModel):
    name: str
    base_credits: float
    default_model: str = Field(..., description="该套餐默认使用的模型 ID")
    
    # 核心改进 1：只存 Model ID 的列表，不再冗余定义模型参数
    allowed_models: List[str] = Field(..., description="该套餐允许使用的模型 ID 列表")
    
    # 核心改进 2：套餐级别的全局折扣（例如 Pro 用户消耗额度打 5 折）
    global_discount: float = Field(default=1.0, description="扣费折扣率，1.0 为不打折")
    
    # 核心改进 3：(可选) 针对特定模型的特殊定价覆盖
    custom_model_ratios: Optional[Dict[str, Dict[str, float]]] = Field(
        default_factory=dict, 
        description="特例：覆盖特定模型的基础费率"
    )
    
    allowed_tools: List[FuncName] = Field(default_factory=list)

# 商业套餐配置变得极其清爽
PLAN_REGISTRY: Dict[str, PlanConfig] = {
    "free": PlanConfig(
        name="Free Plan",
        base_credits=300, # 每个月的默认配额
        default_model="gemini-3.1-pro-preview",
        allowed_models=["gemini-3-flash-preview", "gemini-3-pro-preview", "gemini-3.1-pro-preview", "Qwen3-VL-235B-A22B-Inst"],
        allowed_tools=[]
    ),
    "pro": PlanConfig(
        name="Pro Plan",
        base_credits=1000, # 每个月的默认配额
        default_model="gemini-3.1-pro-preview",
        allowed_models=["gemini-3-flash-preview", "gemini-3-pro-preview", "gemini-3.1-pro-preview", "Qwen3-VL-235B-A22B-Inst"],
        allowed_tools=[]
    )
}
