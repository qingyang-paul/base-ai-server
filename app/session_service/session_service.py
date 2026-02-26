import json
from uuid import UUID
from typing import List, AsyncGenerator, Dict, Any
from datetime import datetime, timezone

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.session_service.core.schema import SessionMeta, SessionMessage, SessionStatus
from app.session_service.core.prompt_registry import SystemPromptScene, PromptRegistry
from app.session_service.session_repo import SessionRepo

from app.chat_service.core.schema import (
    LLMMessage, LLMPayload, StreamReply, StreamEventType, RoleType, 
    UserQuery, ChatHistory, SessionContext
)
from app.chat_service.chat_service import ChatService

from app.subscription_service.core.config import GlobalLLMConfig, MODEL_REGISTRY, PLAN_REGISTRY
from app.subscription_service.core.model import UserSubscriptions

from app.session_service.core.config import SESSION_BUFFER_THRESHOLD

class SessionService:
    def __init__(self, repo: SessionRepo, chat_service: ChatService):
        self.repo = repo
        self.chat_service = chat_service

    async def create_session_meta(
        self,
        session_id: UUID,
        user_id: UUID,
        prompt_scene: SystemPromptScene,
        llm_choice: str,
    ) -> SessionMeta:
        """新建 session 时，插入表信息"""
        now = datetime.now(timezone.utc)
        latest_prompt = PromptRegistry.get_latest_prompt(prompt_scene)
        
        meta = SessionMeta(
            user_id=user_id,
            session_id=session_id,
            title=None,
            created_at=now,
            updated_at=now,
            llm_choice=llm_choice,
            message_seq_id=0,
            status=SessionStatus.ACTIVE,
            prompt_scene=prompt_scene,
            prompt_version=latest_prompt.version
        )
        
        # Save to PG via Repo
        await self.repo.create_session_meta_to_alchemy(meta)
        
        # Also cache to Redis
        await self.repo.redis.set(
            f"session_meta:{session_id}",
            meta.model_dump_json()
        )
        return meta

    async def _translate_session_messages_to_llm_messages(
        self,
        session_messages: List[SessionMessage]
    ) -> List[LLMMessage]:
        """去除多余信息，返回一个ChatService能直接用的消息列表"""
        return [msg.llm_message for msg in session_messages]

    async def _translate_llm_messages_to_session_messages(
        self, 
        llm_messages: List[LLMMessage],
        session_id: UUID,
    ) -> List[SessionMessage]:
        """补充必要的信息，返回SessionService能直接用的消息列表"""
        # 获取最新的 seq_id (假设通过 repo 获取并保证原子性)
        increment = len(llm_messages)
        if increment == 0:
            return []
            
        max_seq = await self.repo.get_next_seq_ids(session_id, increment)
        start_seq = max_seq - increment + 1
        
        # Get the latest meta to know user_id
        meta = await self.repo.smart_get_session_meta(session_id)
        if not meta:
            raise ValueError(f"Session {session_id} not found")

        now = datetime.now(timezone.utc)
        session_msgs = []
        for i, lm in enumerate(llm_messages):
            session_msgs.append(SessionMessage(
                user_id=meta.user_id,
                session_id=session_id,
                created_at=now,
                seq_id=start_seq + i,
                llm_message=lm
            ))
        return session_msgs

    async def _translate_and_save_to_buffer(
        self,
        session_id: UUID,
        llm_messages: List[LLMMessage]
    ):
        """将LLMMessage转化为SessionMessage，存入Redis Buffer和Cache"""
        if not llm_messages: return
        
        session_msgs = await self._translate_llm_messages_to_session_messages(
            llm_messages, session_id
        )
        
        meta = await self.repo.smart_get_session_meta(session_id)
        if meta:
            meta.updated_at = datetime.now(timezone.utc)
            meta.message_seq_id = session_msgs[-1].seq_id
            
            # 保存到 Redis (Cache, Buffer, 更新Meta)
            await self.repo.save_new_messages_pipeline(session_id, session_msgs, meta)

            # Check if buffer threshold was reached
            # We dispatch a Taskiq task here to persist to Postgres
            from app.session_service.core.config import SESSION_BUFFER_THRESHOLD
            buffer_size = await self.repo.redis.zcard(f"session_buffer:{session_id}")
            if buffer_size >= SESSION_BUFFER_THRESHOLD:
                from app.session_service.tasks.persist_session_buffer import persist_session_buffer_task
                # Trigger Taskiq asynchronously
                await persist_session_buffer_task.kiq(session_id=session_id)

    async def load_session_context_to_redis(
        self,
        session_id: UUID
    ):
        """
        从PG拿session的历史会话，
        先看是否需要同步（最后一个seq_id是否匹配）
        全量redis session_cache:{session_id}
        替换session_cache的过程，要保证没有读写
        """
        lock_key = f"lock:session:{session_id}"
        async with self.repo.redis.lock(lock_key, timeout=5):
            # Try to get context smartly (which already falls back to PG & populates redis if missing)
            await self.repo.smart_get_session_messages(session_id)

    async def build_llm_payload(
        self,
        system_prompt: str,
        session_id: UUID,
        user_query_text: str,
        user_id: UUID,
        llm_choice: str
    ) -> LLMPayload:
        """组装 LLMPayload 给 ChatService"""
        
        # 1. 组装 chat_history
        session_msgs = await self.repo.smart_get_session_messages(session_id)
        llm_msgs = await self._translate_session_messages_to_llm_messages(session_msgs)
        chat_history = ChatHistory(messages=llm_msgs)
        
        # 2. 组装 user_query
        user_query = UserQuery(content=user_query_text)
        
        # 3. 组装 session_context (暂定为空 preferences)
        session_context = SessionContext(user_sop_preferences=[])
        
        # 4. 获取用户订阅套餐和允许的工具
        # 为保持解耦，可以通过跨模块查询或在 Dependency 层注入 User Plan.
        # 此处简化：查询数据库得到用户的 Plan。
        stmt = select(UserSubscriptions).where(
            UserSubscriptions.user_id == user_id, 
            UserSubscriptions.status == 'active'
        ).order_by(UserSubscriptions.current_period_end.desc())
        
        result = await self.repo.db.execute(stmt)
        user_sub = result.scalars().first()
        
        tier = user_sub.subscription_tier if user_sub else "free"
        plan_config = PLAN_REGISTRY.get(tier, PLAN_REGISTRY["free"])
        
        allowed_tools = plan_config.allowed_tools
        
        # 5. 调用 ChatService.build_llm_payload
        payload = self.chat_service.build_llm_payload(
            system_prompt=system_prompt,
            chat_history=chat_history,
            user_query=user_query,
            session_context=session_context,
            allowed_tools=allowed_tools
        )
        return payload

    async def build_llm_generation_config(
        self,
        user_id: UUID,
        llm_choice: str
    ) -> GlobalLLMConfig:
        """检查用户的模型权限，生成 GlobalLLMConfig"""
        
        stmt = select(UserSubscriptions).where(
            UserSubscriptions.user_id == user_id,
            UserSubscriptions.status == 'active'
        ).order_by(UserSubscriptions.current_period_end.desc())
        
        result = await self.repo.db.execute(stmt)
        user_sub = result.scalars().first()
        
        tier = user_sub.subscription_tier if user_sub else "free"
        plan_config = PLAN_REGISTRY.get(tier, PLAN_REGISTRY["free"])
        
        if llm_choice not in plan_config.allowed_models:
            # Downgrade or reject
            # Let's downgrade to default
            logger.warning(f"User {user_id} requested {llm_choice} which is not allowed in {tier} plan. Downgrading to {plan_config.default_model}")
            llm_choice = plan_config.default_model
            
        return MODEL_REGISTRY[llm_choice]

    async def handle_agent_stream_reply(
        self,
        user_query_text: str,
        session_id: UUID,
        user_id: UUID,
        prompt_scene: SystemPromptScene = SystemPromptScene.PAL,
        llm_choice: str = "qwen"
    ) -> AsyncGenerator[StreamReply, None]:
        
        # 1. 加载 & 校验上下文 (带锁，防止并发加载重入)
        await self.load_session_context_to_redis(session_id)
        
        # 2. 获取 Meta，处理 Prompt Version
        meta = await self.repo.smart_get_session_meta(session_id)
        if not meta:
            logger.info(f"Session {session_id} not found. Lazily creating a new session.")
            meta = await self.create_session_meta(
                session_id=session_id,
                user_id=user_id,
                prompt_scene=prompt_scene,
                llm_choice=llm_choice
            )
            
        system_prompt = PromptRegistry.get_prompt(meta.prompt_scene, meta.prompt_version)
        
        # 3. 构造下游参数
        generation_config = await self.build_llm_generation_config(user_id, meta.llm_choice)
        llm_payload = await self.build_llm_payload(system_prompt, session_id, user_query_text, user_id, meta.llm_choice)
        
        # 将用户当前查询保存到 Buffer 中以保证一致性
        user_llm_msg = LLMMessage(role=RoleType.USER, content=user_query_text)

        # 这里我们需要准备保存的内容，包括用户最新的一句话
        all_new_messages_to_save: List[LLMMessage] = [user_llm_msg]
        
        # 4. 调用底层 ChatService 拿到流
        # Create context kwargs to pass user_id into tools if they need it
        context_kwargs = {"user_id": str(user_id)}
        
        stream_gen = self.chat_service.chat_stream_with_tools(
            runtime_config=generation_config,
            payload=llm_payload,
            context_kwargs=context_kwargs
        )
        
        # Process the stream
        async for reply in stream_gen:
            if reply.event_type == StreamEventType.TEXT_CHUNK:
                yield reply
            elif reply.event_type == StreamEventType.TOOL_CALL:
                yield reply
            elif reply.event_type == StreamEventType.STATUS:
                yield reply
            elif reply.event_type == StreamEventType.STATS:
                # We can handle stats here if needed
                yield reply
            elif reply.event_type == StreamEventType.ERROR:
                yield reply
            elif reply.event_type == StreamEventType.RUN_FINISH:
                all_new_messages_to_save.extend(reply.generated_messages)
                yield reply
                break
                
        # 此时流已断开，前端已经接收完文本。
        # SessionService 开始独立执行转换和持久化！
        # 聊天结束落库时，也必须抢锁！
        lock_key = f"lock:session:{session_id}"
        async with self.repo.redis.lock(lock_key, timeout=5):
            await self._translate_and_save_to_buffer(
                session_id=session_id,
                llm_messages=all_new_messages_to_save
            )
