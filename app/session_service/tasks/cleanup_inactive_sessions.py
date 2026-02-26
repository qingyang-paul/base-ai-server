from datetime import datetime, timezone
import logging
from uuid import UUID

from taskiq import TaskiqDepends

from app.taskiq import broker
from app.session_service.session_repo import SessionRepo
from app.dependencies import get_session_repo
from app.session_service.core.config import SESSION_INACTIVE_THRESHOLD

logger = logging.getLogger(__name__)

@broker.task(schedule=[{"cron": "*/5 * * * *"}])
async def cleanup_inactive_sessions_task(
    repo: SessionRepo = TaskiqDepends(get_session_repo)
):
    """
    Task 1: 定时任务。找出不活跃的 session，兜底持久化，并清理 Redis。
    """
    logger.info("Starting cleanup of inactive sessions...")
    
    # 1. 遍历所有的 session_meta key
    # 使用 scan_iter 防止一次性 keys() 阻塞 Redis
    async for key in repo.redis.scan_iter(match="session_meta:*"):
        
        # 从 key 中解析出 session_id (格式: session_meta:xxxx-xxxx...)
        session_id_str = key.decode("utf-8").split(":")[1]
        try:
            session_id = UUID(session_id_str)
        except ValueError:
            continue
            
        # 获取 meta
        meta = await repo.get_session_meta_from_redis(session_id)
        if not meta:
            continue
            
        # 计算是否 inactive
        now = datetime.now(timezone.utc)
        time_diff = (now - meta.updated_at).total_seconds()
        
        if time_diff > SESSION_INACTIVE_THRESHOLD:
            # 双重检查锁定
            lock_key = f"lock:session:{session_id}"
            
            # 尝试获取锁，如果获取不到说明用户恰好在发消息，或者 Task 2 正在落库，则跳过本轮
            lock = repo.redis.lock(lock_key, timeout=10, blocking_timeout=1)
            acquired = await lock.acquire()
            
            if acquired:
                try:
                    # 获取锁后，必须再次读取 meta防止在等待锁的期间被更新了
                    fresh_meta = await repo.get_session_meta_from_redis(session_id)
                    if not fresh_meta:
                        continue
                        
                    fresh_time_diff = (now - fresh_meta.updated_at).total_seconds()
                    
                    if fresh_time_diff <= SESSION_INACTIVE_THRESHOLD:
                        continue # 刚刚复活了，放弃清理
                    
                    # 2. 兜底持久化剩余的 Buffer
                    messages = await repo.get_session_buffer_messages(session_id)
                    if messages:
                        await repo.insert_session_messages_to_alchemy(messages)
                        await repo.db.commit()
                        
                    # 3. Buffer 清空后，彻底删除 Redis 里的 Session 痕迹
                    pipeline = repo.redis.pipeline()
                    pipeline.delete(f"session_meta:{session_id}")
                    pipeline.delete(f"session_cache:{session_id}")
                    pipeline.delete(f"session_buffer:{session_id}")
                    pipeline.delete(f"session_seq:{session_id}")
                    await pipeline.execute()
                    
                    logger.info(f"Cleaned up inactive session {session_id}")
                    
                except Exception as e:
                    logger.error(f"Error cleaning up session {session_id}: {e}")
                finally:
                    # 确保锁被释放
                    await lock.release()
