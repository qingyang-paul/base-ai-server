import logging
from uuid import UUID

from taskiq import TaskiqDepends

from app.taskiq import broker
from app.session_service.session_repo import SessionRepo
from app.dependencies import get_session_repo

logger = logging.getLogger(__name__)

@broker.task
async def persist_session_buffer_task(
    session_id: UUID,
    repo: SessionRepo = TaskiqDepends(get_session_repo)
):
    """
    Task 2: 主动触发。当 Service 发现 buffer 达到 threshold 时调用。
    使用方法: await persist_session_buffer_task.kiq(session_id)
    """
    lock_key = f"lock:session:{session_id}"
    
    # 1. 锁定特定 Session 的操作
    # timeout 设置一个合理的值(如 10s)，防止 worker 崩溃导致死锁
    async with repo.redis.lock(lock_key, timeout=10):
        # 2. 读取当前 buffer 里的所有消息        
        # 获取所有 buffer 消息（按 seq_id 从小到大排序）
        messages = await repo.get_session_buffer_messages(session_id) 
        
        if not messages:
            return # 已经被其他 worker 处理过了，直接返回
            
        # 3. 确定 range (取这批消息的最小和最大 seq_id)
        min_seq_id = messages[0].seq_id
        max_seq_id = messages[-1].seq_id
        
        try:
            # 4. 搬运到 Postgres
            await repo.insert_session_messages_to_alchemy(messages)
            await repo.db.commit() 
            
            # 5. 删除 Redis buffer 对应范围的消息
            # 注意开闭区间，如果 Repo 内部做了处理，这里传 max_seq_id 即可
            await repo.delete_session_buffer_by_score(
                session_id=session_id, 
                range_start=min_seq_id, 
                range_end=max_seq_id + 1 
            )
            logger.info(f"Successfully persisted buffer for session {session_id} (seq: {min_seq_id}-{max_seq_id})")
        except Exception as e:
            logger.error(f"Error persisting session {session_id} buffer: {e}")
            await repo.db.rollback()
            raise e
