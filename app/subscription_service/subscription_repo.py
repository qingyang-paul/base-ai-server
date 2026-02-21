import uuid
from decimal import Decimal
from typing import Optional
from datetime import datetime

from sqlalchemy import select, update, func
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.subscription_service.core.model import (
    UserCreditBalance, 
    UserSubscriptions, 
    UsageLedger
)
from app.subscription_service.core.schema import (
    UserSubscriptionUpdate,
    UsageLedgerCreate
)


class SubscriptionRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def lock_user_balance_for_update(self, user_id: uuid.UUID) -> Optional[UserCreditBalance]:
        """必须带排他锁 (FOR UPDATE)，阻塞其他并发的扣费请求"""
        query = (
            select(UserCreditBalance)
            .where(UserCreditBalance.user_id == user_id)
            .with_for_update()
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def update_user_credit_balances(
        self, 
        user_id: uuid.UUID, 
        new_sub_balance: Decimal, 
        new_purchased_balance: Decimal
    ) -> None:
        """执行更新"""
        stmt = (
            update(UserCreditBalance)
            .where(UserCreditBalance.user_id == user_id)
            .values(
                subscription_credits=new_sub_balance,
                purchased_credits=new_purchased_balance
            )
        )
        await self.session.execute(stmt)

    async def insert_usage_ledger(self, ledger_data: UsageLedgerCreate) -> UsageLedger:
        """新增一条流水（Insert 而不是 Update）"""
        ledger_dict = ledger_data.model_dump(exclude_unset=True)
        new_ledger = UsageLedger(**ledger_dict)
        self.session.add(new_ledger)
        return new_ledger
        
    async def update_user_subscriptions(
        self,
        user_id: uuid.UUID,  # 必传：知道要更新哪个用户的订阅
        update_payload: UserSubscriptionUpdate
    ) -> None:
        """更新用户订阅状态"""
        update_data = update_payload.model_dump(exclude_unset=True)
        if not update_data:
            return  # 没有需要更新的字段
            
        stmt = (
            update(UserSubscriptions)
            .where(UserSubscriptions.user_id == user_id)
            .values(**update_data)
        )
        await self.session.execute(stmt)
      
    async def create_user_subscription(self, subscription_data: dict) -> UserSubscriptions:
        """初始化用户订阅记录"""
        new_sub = UserSubscriptions(**subscription_data)
        self.session.add(new_sub)
        return new_sub

    async def create_user_credit_balance(self, balance_data: dict) -> UserCreditBalance:
        """初始化用户额度账户"""
        new_balance = UserCreditBalance(**balance_data)
        self.session.add(new_balance)
        return new_balance

    async def get_expired_active_subscriptions(self) -> list[UserSubscriptions]:
        """查询已过期但状态为 'active' 的订阅"""
        query = (
            select(UserSubscriptions)
            .where(UserSubscriptions.status == 'active')
            .where(UserSubscriptions.current_period_end <= func.now())
            # For update ensures no concurrency issues during Cron processing
            .with_for_update(skip_locked=True)
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def reset_user_subscription_and_credits(
        self,
        user_id: uuid.UUID,
        sub_update: UserSubscriptionUpdate,
        new_sub_balance: Decimal
    ) -> None:
        """同时更新订阅和额度账户"""
        # 更新订阅表
        sub_update_data = sub_update.model_dump(exclude_unset=True)
        if sub_update_data:
            stmt1 = (
                update(UserSubscriptions)
                .where(UserSubscriptions.user_id == user_id)
                .values(**sub_update_data)
            )
            await self.session.execute(stmt1)

        # 更新额度表
        stmt2 = (
            update(UserCreditBalance)
            .where(UserCreditBalance.user_id == user_id)
            .values(
                subscription_credits=new_sub_balance,
                updated_at=func.now()
            )
        )
        await self.session.execute(stmt2)
