from enum import Enum
from pydantic import BaseModel
from uuid import UUID
from datetime import datetime
from typing import Optional
from app.session_service.core.prompt_registry import SystemPromptScene
from app.chat_service.core.schema import LLMMessage

class SessionStatus(str, Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    DELETED = "deleted"

class SessionMeta(BaseModel): 
    user_id: UUID
    session_id: UUID
    title: Optional[str] = None      # 会话标题
    created_at: datetime             # 创建时间
    updated_at: datetime             # 多端校验同步
    llm_choice: str                  # api router 携带参数
    message_seq_id: int              # 最后一条消息的session内seq数
    status: SessionStatus            # 状态管理 active, archived, deleted
    prompt_scene: SystemPromptScene  # 记录这个会话是干嘛的 (e.g., "default_chat")
    prompt_version: str              # 记录这个会话【创建时】使用的 prompt 版本 (e.g., "v1.0")

class SessionMessage(BaseModel):
    user_id: UUID
    session_id: UUID
    created_at: datetime
    seq_id: int                      # session内的自增数
    llm_message: LLMMessage          # import from chat_service/core/schema.py
