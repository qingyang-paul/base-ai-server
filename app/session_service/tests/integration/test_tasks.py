import pytest
import uuid
from datetime import datetime, timezone, timedelta
from app.session_service.core.schema import SessionMeta, SessionMessage, SessionStatus
from app.session_service.core.prompt_registry import SystemPromptScene
from app.chat_service.core.schema import LLMMessage, RoleType
from sqlalchemy import text
from app.session_service.tasks.persist_session_buffer import persist_session_buffer_task
from app.session_service.tasks.cleanup_inactive_sessions import cleanup_inactive_sessions_task
from app.session_service.core.config import SESSION_INACTIVE_THRESHOLD

@pytest.mark.asyncio
async def test_persist_session_buffer_task(repo, db_session, redis_client):
    """
    Test that the task correctly reads the session buffer from redis,
    saves the messages to PostgreSQL, and removes them from the buffer.
    """
    session_id = uuid.uuid4()
    user_id = uuid.uuid4()
    
    # 1. Create a few fake session messages in Redis
    messages = []
    for i in range(1, 6):
        msg = SessionMessage(
            user_id=user_id,
            session_id=session_id,
            created_at=datetime.now(timezone.utc),
            seq_id=i,
            llm_message=LLMMessage(role=RoleType.USER, content=f"Message {i}")
        )
        messages.append(msg)
        
    # Push to redis buffer directly using repo method or directly with redis
    pipeline = redis_client.pipeline()
    buffer_key = f"session_buffer:{session_id}"
    for msg in messages:
        pipeline.zadd(buffer_key, {msg.model_dump_json(): msg.seq_id})
    await pipeline.execute()
    
    # Verify buffer size
    initial_size = await redis_client.zcard(buffer_key)
    assert initial_size == 5

    # 2. Run the task directly (simulating Taskiq worker)
    # The kiq object is the taskiq decorator, the underlying function is available or we can just call it 
    # if it's async def function we can call it directly.
    # Note: If it's decorated with @broker.task, we can call the original async function directly
    # However Taskiq replaces the function. To call the original, it's usually `task_name(...)`
    # Let's see how Taskiq wrapping works. If it complains about `repo` being TaskiqDepends, 
    # we can pass it manually.
    await persist_session_buffer_task(session_id=session_id, repo=repo)
    
    # 3. Assert PostgreSQL contains the messages
    rows = (await db_session.execute(
        text("SELECT * FROM session_messages WHERE session_id = :session_id ORDER BY seq_id ASC"), 
        {"session_id": session_id}
    )).mappings().all()
    
    assert len(rows) == 5
    assert rows[0]["seq_id"] == 1
    assert rows[4]["seq_id"] == 5
    
    # 4. Assert Redis buffer is empty
    final_size = await redis_client.zcard(buffer_key)
    assert final_size == 0


@pytest.mark.asyncio
async def test_cleanup_inactive_sessions_task(repo, db_session, redis_client):
    """
    Test that the cleanup task identifies inactive sessions,
    flushes the remaining buffer to database, and deletes all redis keys.
    """
    session_id = uuid.uuid4()
    user_id = uuid.uuid4()
    
    # 1. Create an inactive SessionMeta deeply in the past
    past_time = datetime.now(timezone.utc) - timedelta(seconds=SESSION_INACTIVE_THRESHOLD + 10)
    
    meta = SessionMeta(
        user_id=user_id,
        session_id=session_id,
        created_at=past_time,
        updated_at=past_time,  # Inactive
        llm_choice="qwen",
        message_seq_id=2,
        status=SessionStatus.ACTIVE,
        prompt_scene=SystemPromptScene.PAL,
        prompt_version="v1.0"
    )
    
    # 2. Create un-persisted buffer messages 
    msg1 = SessionMessage(
        user_id=user_id,
        session_id=session_id,
        created_at=past_time,
        seq_id=1,
        llm_message=LLMMessage(role=RoleType.USER, content="Hello")
    )
    msg2 = SessionMessage(
        user_id=user_id,
        session_id=session_id,
        created_at=past_time,
        seq_id=2,
        llm_message=LLMMessage(role=RoleType.ASSISTANT, content="Hi")
    )
    
    # Insert everything into Redis
    pipeline = redis_client.pipeline()
    pipeline.set(f"session_meta:{session_id}", meta.model_dump_json())
    pipeline.set(f"session_seq:{session_id}", 2)
    pipeline.zadd(f"session_cache:{session_id}", {msg1.model_dump_json(): 1, msg2.model_dump_json(): 2})
    pipeline.zadd(f"session_buffer:{session_id}", {msg1.model_dump_json(): 1, msg2.model_dump_json(): 2})
    await pipeline.execute()
    
    # Verify Redis keys exist
    assert await redis_client.exists(f"session_meta:{session_id}") == 1
    assert await redis_client.zcard(f"session_buffer:{session_id}") == 2
    
    # 3. Execute cron task
    await cleanup_inactive_sessions_task(repo=repo)
    
    # 4. Assert PostgreSQL contains the buffer messages
    rows = (await db_session.execute(
        text("SELECT * FROM session_messages WHERE session_id = :session_id ORDER BY seq_id ASC"), 
        {"session_id": session_id}
    )).mappings().all()
    
    assert len(rows) == 2
    assert rows[0]["seq_id"] == 1
    
    # 5. Assert ALL Redis keys are purged
    assert await redis_client.exists(f"session_meta:{session_id}") == 0
    assert await redis_client.exists(f"session_seq:{session_id}") == 0
    assert await redis_client.exists(f"session_cache:{session_id}") == 0
    assert await redis_client.exists(f"session_buffer:{session_id}") == 0
