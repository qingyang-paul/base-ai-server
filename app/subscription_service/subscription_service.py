from decimal import Decimal
from datetime import datetime, timezone
from uuid import UUID, uuid4
from dateutil.relativedelta import relativedelta
from pydantic import BaseModel

from app.core.logger import logger
from app.subscription_service.core.exceptions import (
    ModelNotFoundError,
    UserBalanceNotFoundError,
    InsufficientCreditsError,
    ConfigurationError,
)

from app.subscription_service.core.config import PLAN_REGISTRY, MODEL_REGISTRY
from app.subscription_service.core.schema import UserSubscriptionUpdate, UsageLedgerCreate
from app.subscription_service.subscription_repo import SubscriptionRepo


class SessionMessage(BaseModel):
    """
    Placeholder class mapping over SessionMessage properties required for process_message_billing.
    """
    user_id: UUID
    session_id: UUID
    message_id: UUID
    model_id: str
    input_tokens: int
    output_tokens: int

class SubscriptionService:
    def __init__(self, repo: SubscriptionRepo):
        self.repo = repo

    def calculate_deduction_split(self, 
            required_credits: Decimal, 
            current_sub_credits: Decimal, 
            current_purchased_credits: Decimal) -> dict:
        """
        纯内存计算：优先扣套餐，超出扣充值
        返回: 扣费明细字典，例如 {"sub_deducted": 5, "purchased_deducted": 2, "is_sufficient": True}
        """
        deduct_sub = Decimal(0)
        deduct_purchased = Decimal(0)
        
        if required_credits <= current_sub_credits:
            deduct_sub = required_credits
        else:
            deduct_sub = current_sub_credits
            remaining_required = required_credits - current_sub_credits
            
            if remaining_required <= current_purchased_credits:
                deduct_purchased = remaining_required
            else:
                return {
                    "sub_deducted": Decimal(0),
                    "purchased_deducted": Decimal(0),
                    "is_sufficient": False,
                    "shortfall": remaining_required - current_purchased_credits
                }
        
        return {
            "sub_deducted": deduct_sub,
            "purchased_deducted": deduct_purchased,
            "is_sufficient": True
        }

    def _calculate_cost_from_tokens(self, message: SessionMessage) -> Decimal:
        config = MODEL_REGISTRY.get(message.model_id)
        if not config:
            raise ModelNotFoundError(f"Model ID '{message.model_id}' not found in registry.")

        prompt_cost = message.input_tokens * config.base_prompt_ratio
        completion_cost = message.output_tokens * config.base_completion_ratio

        return Decimal(str(prompt_cost + completion_cost))

    async def handle_purchase_credit(self, user_id: str, purchased_credits: int):
        uid = UUID(user_id) if isinstance(user_id, str) else user_id
        
        balance_record = await self.repo.lock_user_balance_for_update(uid)
        if not balance_record:
            raise UserBalanceNotFoundError(f"No credit balance found for user {uid}")
            
        new_purchased_balance = balance_record.purchased_credits + Decimal(purchased_credits)
        await self.repo.update_user_credit_balances(
            user_id=uid,
            new_sub_balance=balance_record.subscription_credits,
            new_purchased_balance=new_purchased_balance
        )
        await self.repo.session.commit()

    async def process_message_billing(self, message: SessionMessage) -> UsageLedgerCreate:
            """
            核心计费入口：从SessionMessage 提取user_id, session_id, token_usage
            """
            # 1. 计算本次需要多少钱
            required_credits = self._calculate_cost_from_tokens(message)

            # --- 开启数据库事务的保护伞 ---
            try:
                # 2. 从 Repo 加锁获取当前余额 (SELECT FOR UPDATE)
                # 注意：建议直接传 UUID 对象，SQLAlchemy 能自动处理，不需要 str()
                balance_record = await self.repo.lock_user_balance_for_update(message.user_id)
                
                if not balance_record:
                    raise UserBalanceNotFoundError(f"未找到用户 {message.user_id} 的资产账户")
                    
                # 3. 调用 calculate_deduction_split 计算应该怎么扣
                split = self.calculate_deduction_split(
                    required_credits, 
                    balance_record.subscription_credits,
                    balance_record.purchased_credits
                )
                
                # 4. 如果余额不足，抛出异常
                if not split.get("is_sufficient", True): # 假设你的 split 里有 is_sufficient 字段
                    raise InsufficientCreditsError(f"余额不足。缺口: {split.get('shortfall')}")
                    
                # 5. 【核心优化】利用 ORM 魔法直接更新余额，无需单独调 Repo 方法
                new_sub_balance = balance_record.subscription_credits - split["sub_deducted"]
                new_purchased_balance = balance_record.purchased_credits - split["purchased_deducted"]
                
                # 直接赋值，SQLAlchemy Session 会监控到这两个字段变“脏”了
                balance_record.subscription_credits = new_sub_balance
                balance_record.purchased_credits = new_purchased_balance
                balance_record.updated_at = datetime.now(timezone.utc)
                
                # 6. 调用 Repo 写入流水 (Ledger)
                ledger_data = UsageLedgerCreate(
                    id=uuid4(),
                    user_id=message.user_id,
                    session_id=message.session_id,
                    message_id=message.message_id,
                    sub_credits_deducted=split["sub_deducted"],
                    purchased_credits_deducted=split["purchased_deducted"],
                    sub_balanced_after=new_sub_balance,
                    purchased_balanced_after=new_purchased_balance,
                    created_at=datetime.now(timezone.utc)
                )
                # 确保你的 insert_usage_ledger 里只做 session.add(ledger)，不要自己 commit
                await self.repo.insert_usage_ledger(ledger_data)
                
                # 7. --- 提交数据库事务 (Commit) ---
                # 这一步会同时发送 UPDATE (改余额) 和 INSERT (加流水)，并释放排他锁！
                await self.repo.session.commit()
                
                return ledger_data

            except UserBalanceNotFoundError as e:
                await self.repo.session.rollback()
                logger.warning(str(e))
                raise e
                
            except InsufficientCreditsError as e:
                # 业务类异常（如余额不足），正常回滚，向上抛出给 HTTP 层返回 402 Payment Required
                await self.repo.session.rollback()
                logger.info(f"用户 {message.user_id} 扣费失败: 余额不足")
                raise e
                
            except Exception as e:
                # 兜底：未知的系统级异常（如数据库断连、数据类型验证失败）
                # 必须回滚，防止死锁！
                await self.repo.session.rollback()
                logger.error(f"计费过程发生未知系统异常，已回滚事务。User: {message.user_id}, Error: {str(e)}")
                raise e

    async def handle_subscription_pro(self, user_id: str, auto_renew: bool, end_at: datetime):
        uid = UUID(user_id) if isinstance(user_id, str) else user_id
        payload = UserSubscriptionUpdate(
            subscription_tier='pro',
            auto_renew=auto_renew,
            current_period_end=end_at,
            status='active'
        )
        await self.repo.update_user_subscriptions(user_id=uid, update_payload=payload)
        await self.repo.session.commit()

    async def get_available_credits(self, user_id: str) -> Decimal:
        uid = UUID(user_id) if isinstance(user_id, str) else user_id
        # lock_user_balance_for_update can serve as a read if we don't have a plaintext read.
        # But we must rollback so we don't hold the lock if unneeded.
        balance = await self.repo.lock_user_balance_for_update(uid)
        if not balance:
            await self.repo.session.rollback()
            return Decimal(0)
            
        avail = balance.subscription_credits + balance.purchased_credits
        await self.repo.session.rollback()
        return avail

    async def handle_user_cancel_renewal(self, user_id: str):
        """场景 A：用户在前端点击了【取消自动续费】"""
        uid = UUID(user_id) if isinstance(user_id, str) else user_id
        payload = UserSubscriptionUpdate(auto_renew=False)
        await self.repo.update_user_subscriptions(user_id=uid, update_payload=payload)
        await self.repo.session.commit()

    async def handle_user_registration(self, user_id: UUID):
        """
        处理新用户注册：初始化免费订阅和基础额度
        """
        # 1. 获取系统配置的 Free 套餐基准参数
        free_plan = PLAN_REGISTRY.get("free")
        if not free_plan:
            raise ConfigurationError("系统配置错误：未找到 'free' 套餐定义")

        now_utc = datetime.now(timezone.utc)
        
        # 2. 组装订阅表初始数据
        subscription_data = {
            "id": uuid4(),
            "user_id": user_id,
            "subscription_tier": "free",
            "current_period_start": now_utc,
            "current_period_end": now_utc + relativedelta(months=1),
            "auto_renew": False,
            "status": "active",
            "stripe_subscription_id": ""
        }

        # 3. 组装额度表初始数据
        balance_data = {
            "user_id": user_id,
            "subscription_credits": Decimal(str(free_plan.base_credits)),
            "purchased_credits": Decimal(0),
            "updated_at": now_utc
        }

        # 4. 执行数据库事务
        try:
            await self.repo.create_user_subscription(subscription_data)
            await self.repo.create_user_credit_balance(balance_data)
            
            # 统一提交事务，确保两张表同时写入成功
            await self.repo.session.commit()
            logger.info(f"成功为新用户 {user_id} 初始化 Free 订阅和额度。")
            
        except Exception as e:
            # 如果任何一步出错（如 user_id 冲突），回滚事务，防止脏数据
            await self.repo.session.rollback()
            logger.error(f"为新用户 {user_id} 初始化订阅失败: {str(e)}")
            raise e
