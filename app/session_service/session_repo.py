import json
from uuid import UUID
from typing import List, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from redis.asyncio import Redis

from app.session_service.core.schema import SessionMeta, SessionMessage
from app.session_service.core.model import SessionMetaModel, SessionMessageModel


class SessionRepo:
    def __init__(self, redis_client: Redis, db_session: AsyncSession):
        self.redis = redis_client
        self.db = db_session  # SQLAlchemy async session

    # ==================== Redis 操作 ====================

    async def get_next_seq_ids(self, session_id: UUID, increment: int = 1) -> int:
        """
        原子获取下一个 seq_id。
        如果本次有 3 条消息要存，传入 increment=3，返回最大的 seq_id，
        方便上层给每条消息倒推分配 seq_id。
        """
        key = f"session_seq:{session_id}"
        return await self.redis.incrby(key, increment)

    async def save_new_messages_pipeline(
        self, 
        session_id: UUID, 
        messages: List[SessionMessage],
        latest_meta: SessionMeta  # 用于同步更新 updated_at 和 message_seq_id
    ):
        """
        【核心方法】使用 Pipeline 保证 Cache、Buffer、Meta 的原子写入
        """
        cache_key = f"session_cache:{session_id}"
        buffer_key = f"session_buffer:{session_id}"
        meta_key = f"session_meta:{session_id}"

        # 构造 Zset 需要的 mapping: { JSON字符串: score(seq_id) }
        zset_mapping = {
            msg.model_dump_json(): msg.seq_id for msg in messages
        }

        pipeline = self.redis.pipeline()
        
        # 1. 写入 Cache (ZADD)
        pipeline.zadd(cache_key, zset_mapping)
        
        # 2. 写入 Buffer (ZADD)
        pipeline.zadd(buffer_key, zset_mapping)
        
        # 3. 更新 Meta
        pipeline.set(meta_key, latest_meta.model_dump_json())

        # 批量执行
        await pipeline.execute()

    async def get_session_meta_from_redis(self, session_id: UUID) -> Optional[SessionMeta]:
        """从 Redis 获取会话元数据"""
        data = await self.redis.get(f"session_meta:{session_id}")
        return SessionMeta.model_validate_json(data) if data else None

    async def delete_session_buffer_by_score(self, session_id: UUID, range_start: int, range_end: int):
        """
        消费 Buffer 后删除记录
        Redis ZREMRANGEBYSCORE: 默认是闭区间 [start, end]
        如果想要 [start, end) 排除 end，给 max 加上 '(' 即可
        """
        key = f"session_buffer:{session_id}"
        # 例如 range_start=1, range_end=10 -> max_score = "(10"
        max_score = f"({range_end}" 
        await self.redis.zremrangebyscore(key, min=range_start, max=max_score)

    async def get_session_cache_messages(self, session_id: UUID, limit: int = 50) -> List[SessionMessage]:
        """从 Redis 获取最近的 N 条上下文"""
        key = f"session_cache:{session_id}"
        # ZREVRANGE 获取最新的 N 条，再反转回正序
        # redis return default bytes, need to decode
        items = await self.redis.zrevrange(key, 0, limit - 1)
        messages = [SessionMessage.model_validate_json(item) for item in reversed(items)]
        return messages

    async def get_session_buffer_messages(self, session_id: UUID) -> List[SessionMessage]:
        """读取当前 buffer 里的所有消息"""
        key = f"session_buffer:{session_id}"
        items = await self.redis.zrange(key, 0, -1)
        return [SessionMessage.model_validate_json(item) for item in items]

    # ==================== PostgreSQL 操作 ====================

    async def insert_session_messages_to_alchemy(self, messages: List[SessionMessage]):
        """异步落库 Worker 调用：将一批消息写入 PG"""
        db_messages = []
        for msg in messages:
            db_messages.append(SessionMessageModel(
                user_id=msg.user_id,
                session_id=msg.session_id,
                created_at=msg.created_at,
                seq_id=msg.seq_id,
                llm_message=msg.llm_message.model_dump(mode='json')
            ))
        self.db.add_all(db_messages)
        # Flush or let caller commit later
        await self.db.flush()

    async def read_session_messages_from_alchemy(self, session_id: UUID, limit: int = 50) -> List[SessionMessage]:
        """当 Redis Cache 丢失或用户翻阅历史时，从 PG 兜底读取"""
        stmt = (
            select(SessionMessageModel)
            .where(SessionMessageModel.session_id == session_id)
            .order_by(SessionMessageModel.seq_id.desc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        db_messages = result.scalars().all()
        
        # Convert back and reverse to chronological order
        return [
            SessionMessage(
                user_id=m.user_id,
                session_id=m.session_id,
                created_at=m.created_at,
                seq_id=m.seq_id,
                llm_message=m.llm_message
            )
            for m in reversed(db_messages)
        ]
  
    async def create_session_meta_to_alchemy(self, session_meta: SessionMeta):
        """新建一个session meta 信息"""
        db_meta = SessionMetaModel(**session_meta.model_dump())
        self.db.add(db_meta)
        await self.db.flush()
      
    async def read_session_meta_from_alchemy(self, session_id: UUID) -> Optional[SessionMeta]:
        """从PG兜底读取"""
        stmt = select(SessionMetaModel).where(SessionMetaModel.session_id == session_id)
        result = await self.db.execute(stmt)
        db_meta = result.scalars().first()
        if not db_meta:
            return None
            
        # Manually convert status Enum to string if it comes back as Enum object
        # Pydantic will handle the validation
        return SessionMeta.model_validate(db_meta, from_attributes=True)
      
    async def update_session_meta_to_alchemy(self, session_meta: SessionMeta):
        """从PG更新SessionMeta"""
        update_data = session_meta.model_dump(exclude={"session_id"})
        stmt = (
            update(SessionMetaModel)
            .where(SessionMetaModel.session_id == session_meta.session_id)
            .values(**update_data)
        )
        await self.db.execute(stmt)
        await self.db.flush()
      
    # ==================== Smart 操作 ====================
    # 对于Service来说，并不在乎是从哪里读取的信息，这里要写统一读取接口

    async def smart_get_session_meta(self, session_id: UUID) -> Optional[SessionMeta]:
        meta = await self.get_session_meta_from_redis(session_id)
        if meta:
            return meta

        meta = await self.read_session_meta_from_alchemy(session_id)
        if meta:
            pipeline = self.redis.pipeline()
            # 查到后直接回写 Redis，【不设置 TTL】，等待 Worker 审判
            pipeline.set(f"session_meta:{session_id}", meta.model_dump_json())
            # 同时将 message_seq_id 恢复到 redis
            pipeline.setnx(f"session_seq:{session_id}", meta.message_seq_id)
            await pipeline.execute()
        return meta

    async def smart_get_session_messages(self, session_id: UUID, limit: int = 50) -> List[SessionMessage]:
        messages = await self.get_session_cache_messages(session_id, limit)
        if messages and len(messages) > 0:
            return messages

        messages = await self.read_session_messages_from_alchemy(session_id, limit)
        if messages:
            pipeline = self.redis.pipeline()
            cache_key = f"session_cache:{session_id}"
            seq_key = f"session_seq:{session_id}"

            zset_mapping = {msg.model_dump_json(): msg.seq_id for msg in messages}
            if zset_mapping:
                pipeline.zadd(cache_key, zset_mapping)

                max_seq = max(msg.seq_id for msg in messages)
                pipeline.set(seq_key, max_seq)

                await pipeline.execute()

        return messages
