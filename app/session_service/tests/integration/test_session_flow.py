import pytest
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select

from app.session_service.core.schema import SessionMeta, SessionStatus, SessionMessage
from app.session_service.core.model import SessionMetaModel, SessionMessageModel
from app.session_service.core.prompt_registry import SystemPromptScene, PromptMeta
from app.chat_service.core.schema import LLMMessage, RoleType
from app.subscription_service.core.model import UserSubscriptions

# Ensure standard system prompts are mocked inside test
from unittest.mock import patch

@pytest.mark.asyncio
async def test_create_session_flow(session_service, repo):
    session_id = uuid.uuid4()
    user_id = uuid.uuid4()
    
    # Needs to patch PromptRegistry to not rely on physical files
    mock_prompt_meta = PromptMeta(scene=SystemPromptScene.PAL, version="v1.0", description="test", content="System PAL")
    
    with patch("app.session_service.session_service.PromptRegistry.get_latest_prompt", return_value=mock_prompt_meta):
        meta = await session_service.create_session_meta(
            session_id=session_id,
            user_id=user_id,
            prompt_scene=SystemPromptScene.PAL,
            llm_choice="gpt-4"
        )
        
        # 1. Verify returned Meta
        assert meta.session_id == session_id
        assert meta.status == SessionStatus.ACTIVE
        
        # 2. Verify Database Persistence
        db_meta = await repo.read_session_meta_from_alchemy(session_id)
        assert db_meta is not None
        assert db_meta.user_id == user_id
        
        # 3. Verify Redis Cache
        redis_meta = await repo.get_session_meta_from_redis(session_id)
        assert redis_meta is not None
        assert redis_meta.user_id == user_id


@pytest.mark.asyncio
async def test_translate_and_save_to_buffer(session_service, repo):
    session_id = uuid.uuid4()
    user_id = uuid.uuid4()
    
    # Seed Meta inside postgres and redis
    mock_prompt_meta = PromptMeta(scene=SystemPromptScene.PAL, version="v1.0", description="test", content="System PAL")
    with patch("app.session_service.session_service.PromptRegistry.get_latest_prompt", return_value=mock_prompt_meta):
        meta = await session_service.create_session_meta(
            session_id=session_id,
            user_id=user_id,
            prompt_scene=SystemPromptScene.PAL,
            llm_choice="gpt-4"
        )
        
    llm_msgs = [
        LLMMessage(role=RoleType.USER, content="Hello"),
        LLMMessage(role=RoleType.ASSISTANT, content="Hi there!")
    ]
    
    await session_service._translate_and_save_to_buffer(session_id, llm_msgs)
    
    # 1. Verify Buffer
    buffer_msgs = await repo.get_session_buffer_messages(session_id)
    assert len(buffer_msgs) == 2
    assert buffer_msgs[0].seq_id == 1
    assert buffer_msgs[1].seq_id == 2
    assert buffer_msgs[0].llm_message.content == "Hello"
    
    # 2. Verify Cache
    cache_msgs = await repo.get_session_cache_messages(session_id, limit=50)
    assert len(cache_msgs) == 2
    assert cache_msgs[0].seq_id == 1
    
    # 3. Verify Meta sequence tracking
    redis_meta = await repo.get_session_meta_from_redis(session_id)
    assert redis_meta.message_seq_id == 2


@pytest.mark.asyncio
async def test_smart_get_session_messages_fallback(session_service, repo):
    session_id = uuid.uuid4()
    user_id = uuid.uuid4()
    
    # Insert 2 messages directly to Postgres
    msg1 = SessionMessageModel(session_id=session_id, user_id=user_id, seq_id=1, llm_message={"role": "user", "content": "PG 1"})
    msg2 = SessionMessageModel(session_id=session_id, user_id=user_id, seq_id=2, llm_message={"role": "assistant", "content": "PG 2"})
    repo.db.add_all([msg1, msg2])
    await repo.db.flush()
    
    # Redis is empty right now, calling smart fetch should pull from PG then populate Redis Cache
    msgs = await repo.smart_get_session_messages(session_id, limit=50)
    
    assert len(msgs) == 2
    assert msgs[0].seq_id == 1
    assert msgs[1].seq_id == 2
    
    # Check if redis cache was populated
    cache_msgs = await repo.get_session_cache_messages(session_id, limit=50)
    assert len(cache_msgs) == 2
    assert cache_msgs[0].llm_message.content == "PG 1"
    
    # Check if session_seq was populated
    seq = await repo.redis.get(f"session_seq:{session_id}")
    assert seq is not None
    assert int(seq) == 2
