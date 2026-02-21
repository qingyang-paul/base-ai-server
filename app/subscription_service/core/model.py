import uuid
from datetime import datetime
from typing import Optional, Literal
from decimal import Decimal

from sqlalchemy import String, Boolean, DateTime, Numeric, Enum, Numeric
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import UUID

from app.core.model import Base

class UserSubscriptions(Base):
    __tablename__ = "user_subscriptions"
    
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True, nullable=False)
    subscription_tier: Mapped[str] = mapped_column(String, nullable=False) # 'free', 'pro'
    current_period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    current_period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    auto_renew: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String, nullable=False) # 'active', 'canceled', 'past_due', 'trialing'
    stripe_subscription_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)

class UserCreditBalance(Base):
    __tablename__ = "user_credit_balances"
    
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    subscription_credits: Mapped[Decimal] = mapped_column(Numeric(precision=10, scale=4), nullable=False, default=0)
    purchased_credits: Mapped[Decimal] = mapped_column(Numeric(precision=10, scale=4), nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class UsageLedger(Base):
    __tablename__ = "usage_ledgers"
    
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True, nullable=False)
    message_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True, nullable=False)
    
    # 拆分扣费明细
    sub_credits_deducted: Mapped[Decimal] = mapped_column(Numeric(precision=10, scale=4), nullable=False)
    purchased_credits_deducted: Mapped[Decimal] = mapped_column(Numeric(precision=10, scale=4), nullable=False)
    
    # 拆分余额快照
    sub_balanced_after: Mapped[Decimal] = mapped_column(Numeric(precision=10, scale=4), nullable=False)
    purchased_balanced_after: Mapped[Decimal] = mapped_column(Numeric(precision=10, scale=4), nullable=False)
