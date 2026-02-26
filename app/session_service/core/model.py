import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import String, Integer, DateTime, JSON, Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import UUID as PGUUID

from app.core.model import Base
from app.session_service.core.schema import SessionStatus

class SessionMetaModel(Base):
    __tablename__ = "session_meta"

    # UUID fields stringified to match overall application schemas or PGUUID if using PostgreSQL exclusively.
    # We will use Python uuid.UUID mapped via SQLAlchemy Uuid type for native matching if possible,
    # but since AuthModel uses String, we'll keep it simple: mapped_column(PGUUID(as_uuid=True)) is ideal 
    # to perfectly match the pydantic schema which uses `uuid.UUID`. Let's use PGUUID(as_uuid=True).
    user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    session_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    
    title: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    llm_choice: Mapped[str] = mapped_column(String)
    message_seq_id: Mapped[int] = mapped_column(Integer, default=0)
    
    status: Mapped[SessionStatus] = mapped_column(SQLEnum(SessionStatus))
    prompt_scene: Mapped[str] = mapped_column(String)
    prompt_version: Mapped[str] = mapped_column(String)


class SessionMessageModel(Base):
    __tablename__ = "session_messages"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    session_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    seq_id: Mapped[int] = mapped_column(Integer)
    
    # Stores the raw LLMMessage schema as JSON
    llm_message: Mapped[dict] = mapped_column(JSON)
