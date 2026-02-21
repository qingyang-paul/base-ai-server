import uuid
from taskiq import TaskiqDepends

from app.core.logger import logger
from app.taskiq import broker
from app.subscription_service.subscription_service import SubscriptionService
from app.dependencies import get_subscription_service

@broker.task(task_name="init_user_subscription")
async def init_user_subscription_task(
    user_id_str: str,
    service: SubscriptionService = TaskiqDepends(get_subscription_service)
):
    """
    Taskiq Worker 执行的具体任务：为新用户初始化订阅和额度
    """
    user_id = uuid.UUID(user_id_str)
    logger.info(f"Taskiq 接收到新用户初始化任务: {user_id}")
    
    try:
        await service.handle_user_registration(user_id=user_id)
        logger.info(f"成功为新用户 {user_id} 初始化订阅和额度任务")
    except Exception as e:
        logger.error(f"用户 {user_id} 初始化订阅失败: {e}")
        raise e
