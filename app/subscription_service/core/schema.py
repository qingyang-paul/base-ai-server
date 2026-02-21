from pydantic import BaseModel, Field
from typing import List, Optional, Literal
from datetime import datetime
from uuid import UUID
from decimal import Decimal

# ==========================================
# 1. 单个套餐/层级的配置 -> 用于订阅页面的展示
# ==========================================
class PlanDetailResponse(BaseModel):
    name: str
    base_credits: Decimal
    default_model: str
    allowed_models: List[str] # 告诉前端这个套餐能选哪些模型

# ==========================================
# 2. 用户订阅信息 （读 >> 写）
# ==========================================
class UserSubscriptionPlan(BaseModel):
    user_id: UUID
    subscription_plan: str 
    available_credits: Decimal # 注意这里类型要和数据库对齐
    model_choice: str 
    
    # 鉴权逻辑：判断该模型是否在当前套餐的允许名单中
    def can_access_model(self, model_name: str, allowed_models: List[str]) -> bool:
        return model_name in allowed_models

# ==========================================
# 3. 订阅状态更新载荷 (支持部分更新 Partial Update)
# ==========================================
class UserSubscriptionUpdate(BaseModel):
    """
    用于系统内部或 Webhook 更新用户订阅状态的 DTO。
    所有字段均为 Optional，只有显式传入的字段才会被更新到数据库。
    """
    subscription_tier: Optional[Literal['free', 'pro']] = Field(
        default=None, description="订阅等级 (升级/降级时触发)"
    )
    current_period_start: Optional[datetime] = Field(
        default=None, description="当前计费周期开始时间 (续费成功时更新)"
    )
    current_period_end: Optional[datetime] = Field(
        default=None, description="当前计费周期结束时间 (续费成功时更新)"
    )
    auto_renew: Optional[bool] = Field(
        default=None, description="是否自动续费 (用户主动开启/关闭时更新)"
    )
    status: Optional[Literal['active', 'canceled', 'past_due', 'trialing']] = Field(
        default=None, description="订阅状态 (扣款失败、取消、正常活跃时更新)"
    )
    stripe_subscription_id: Optional[str] = Field(
        default=None, description="绑定的外部支付网关 ID"
    )

# ==========================================
# 4. 额度流水创建载荷 (Usage Ledger Create DTO)
# ==========================================
class UsageLedgerCreate(BaseModel):
    """
    用于插入新流水的 DTO，确保财务对账数据的绝对结构化和类型安全。
    """
    user_id: UUID
    session_id: UUID
    message_id: UUID
    
    # 扣费明细
    sub_credits_deducted: Decimal = Field(..., description="本次扣除的套餐额度")
    purchased_credits_deducted: Decimal = Field(..., description="本次扣除的充值额度")
    
    # 扣费后的余额快照（防线）
    sub_balanced_after: Decimal = Field(..., description="扣费后的套餐余额快照")
    purchased_balanced_after: Decimal = Field(..., description="扣费后的充值余额快照")

    # 可选字段：如果数据库层没有设置 default=uuid4 / default=func.now()，可以在这里传入
    id: Optional[UUID] = None
    created_at: Optional[datetime] = None
