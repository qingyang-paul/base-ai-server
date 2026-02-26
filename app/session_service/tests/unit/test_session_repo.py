import pytest
from unittest.mock import AsyncMock
import uuid
from datetime import datetime, timezone
from app.session_service.core.schema import SessionMessage, SessionMeta, SessionStatus
from app.session_service.core.prompt_registry import SystemPromptScene
from app.chat_service.core.schema import LLMMessage, RoleType

@pytest.mark.asyncio
async def test_get_next_seq_ids(mock_repo):
    session_id = uuid.uuid4()
    mock_repo.redis.incrby.return_value = 5

    result = await mock_repo.get_next_seq_ids(session_id, increment=3)
    
    assert result == 5
    mock_repo.redis.incrby.assert_called_once_with(f"session_seq:{session_id}", 3)


@pytest.mark.asyncio
async def test_save_new_messages_pipeline(mock_repo):
    session_id = uuid.uuid4()
    user_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    
    meta = SessionMeta(
        user_id=user_id, session_id=session_id, created_at=now, updated_at=now,
        llm_choice="gpt-4", message_seq_id=2, status=SessionStatus.ACTIVE,
        prompt_scene=SystemPromptScene.PAL, prompt_version="v1.0"
    )
    
    msg1 = SessionMessage(
        user_id=user_id, session_id=session_id, created_at=now, seq_id=1,
        llm_message=LLMMessage(role=RoleType.USER, content="Hello")
    )
    msg2 = SessionMessage(
        user_id=user_id, session_id=session_id, created_at=now, seq_id=2,
        llm_message=LLMMessage(role=RoleType.ASSISTANT, content="Hi")
    )
    
    pipeline_mock = mock_repo.redis.pipeline.return_value
    
    await mock_repo.save_new_messages_pipeline(session_id, [msg1, msg2], meta)
    
    # Assert pipeline methods were called correctly
    assert pipeline_mock.zadd.call_count == 2
    pipeline_mock.set.assert_called_once_with(
        f"session_meta:{session_id}", meta.model_dump_json()
    )
    pipeline_mock.execute.assert_called_once()
