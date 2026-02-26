import pytest
from unittest.mock import AsyncMock, patch
import uuid
from datetime import datetime, timezone
from typing import List

from app.session_service.core.schema import SessionMessage, SessionMeta, SessionStatus
from app.session_service.core.prompt_registry import SystemPromptScene, PromptMeta
from app.chat_service.core.schema import LLMMessage, RoleType, LLMPayload, StreamReply, StreamEventType, MessageChunkEvent

@pytest.mark.asyncio
async def test_create_session_meta(session_service):
    # Setup
    session_id = uuid.uuid4()
    user_id = uuid.uuid4()
    scene = SystemPromptScene.PAL
    llm_choice = "gpt-4"
    
    # Mock registry
    mock_prompt_meta = PromptMeta(scene=scene, version="v1.0", description="test", content="System")
    with patch("app.session_service.session_service.PromptRegistry.get_latest_prompt", return_value=mock_prompt_meta):
        session_service.repo.create_session_meta_to_alchemy = AsyncMock()
        session_service.repo.redis.set = AsyncMock()

        # Act
        meta = await session_service.create_session_meta(session_id, user_id, scene, llm_choice)

        # Assert
        assert meta.session_id == session_id
        assert meta.user_id == user_id
        assert meta.prompt_version == "v1.0"
        
        session_service.repo.create_session_meta_to_alchemy.assert_called_once_with(meta)
        session_service.repo.redis.set.assert_called_once()


@pytest.mark.asyncio
async def test_translate_llm_messages_to_session_messages(session_service):
    session_id = uuid.uuid4()
    user_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    
    llm_msgs = [
        LLMMessage(role=RoleType.USER, content="Query"),
        LLMMessage(role=RoleType.ASSISTANT, content="Answer"),
    ]
    
    meta = SessionMeta(
        user_id=user_id, session_id=session_id, created_at=now, updated_at=now,
        llm_choice="gpt-4", message_seq_id=0, status=SessionStatus.ACTIVE,
        prompt_scene=SystemPromptScene.PAL, prompt_version="v1.0"
    )
    
    session_service.repo.get_next_seq_ids = AsyncMock(return_value=2)
    session_service.repo.smart_get_session_meta = AsyncMock(return_value=meta)
    
    # Act
    session_msgs = await session_service._translate_llm_messages_to_session_messages(llm_msgs, session_id)
    
    # Assert
    assert len(session_msgs) == 2
    assert session_msgs[0].seq_id == 1
    assert session_msgs[0].llm_message.content == "Query"
    assert session_msgs[1].seq_id == 2
    assert session_msgs[-1].user_id == user_id
