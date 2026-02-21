from decimal import Decimal
from taskiq import TaskiqDepends

from app.core.logger import logger
from app.taskiq import broker
from app.subscription_service.subscription_repo import SubscriptionRepo
from app.dependencies import get_subscription_repo
from app.subscription_service.core.config import PLAN_REGISTRY
from app.subscription_service.core.schema import UserSubscriptionUpdate
from dateutil.relativedelta import relativedelta

@broker.task(schedule=[{"cron": "0 0 * * *"}])
async def reset_expired_subscriptions_and_credits(
    repo: SubscriptionRepo = TaskiqDepends(get_subscription_repo)
):
    """
    扫描并处理所有已到期的订阅
    """
    logger.info("开始执行订阅周期重置与额度刷新任务...")
    
    try:
        expired_subs = await repo.get_expired_active_subscriptions()
        logger.info(f"找到 {len(expired_subs)} 个已到期的活跃订阅需要处理。")
        
        for sub in expired_subs:
            plan_config = PLAN_REGISTRY.get(sub.subscription_tier)
            if not plan_config:
                logger.error(f"用户 {sub.user_id} 的套餐配置 '{sub.subscription_tier}' 不存在，跳过。")
                continue
                
            base_credits = Decimal(str(plan_config.base_credits))
            
            if sub.auto_renew:
                # 场景 A：自动续费开启
                # 推进计费周期（往后加一个月）
                new_start = sub.current_period_end
                new_end = new_start + relativedelta(months=1)
                
                sub_update = UserSubscriptionUpdate(
                    current_period_start=new_start,
                    current_period_end=new_end
                )
                new_sub_balance = base_credits
                logger.info(f"用户 {sub.user_id} 自动续费：周期后延一个月，重置套餐额度为 {new_sub_balance}。")
                
            else:
                # 场景 B：自动续费关闭，订阅到期自然失效
                sub_update = UserSubscriptionUpdate(
                    status="canceled"
                )
                new_sub_balance = Decimal(0)
                logger.info(f"用户 {sub.user_id} 订阅到期失效：状态更新为 canceled，重置套餐额度为 0。")
                
            try:
                await repo.reset_user_subscription_and_credits(
                    user_id=sub.user_id,
                    sub_update=sub_update,
                    new_sub_balance=new_sub_balance
                )
                await repo.session.commit()
            except Exception as e:
                await repo.session.rollback()
                logger.error(f"处理用户 {sub.user_id} 的订阅重置失败: {e}")
                
        logger.info("订阅周期重置与额度刷新任务执行完成。")
            
    except Exception as e:
        logger.error(f"执行订阅重置任务发生错误: {e}")
        raise e
