import pytest
import pytest_asyncio
import uuid
from decimal import Decimal
from datetime import datetime, timezone, timedelta
from sqlalchemy import select

from app.subscription_service.core.model import UserCreditBalance, UserSubscriptions, UsageLedger
from app.subscription_service.core.schema import UsageLedgerCreate, UserSubscriptionUpdate
from app.subscription_service.subscription_repo import SubscriptionRepo

@pytest.fixture
def test_user_id() -> uuid.UUID:
    return uuid.uuid4()

@pytest.mark.asyncio
async def test_create_and_fetch_user_credit_balance(repo: SubscriptionRepo, test_user_id: uuid.UUID):
    # Test Create
    balance_data = {
        "user_id": test_user_id,
        "subscription_credits": Decimal("100.0"),
        "purchased_credits": Decimal("50.0")
    }
    await repo.create_user_credit_balance(balance_data)
    await repo.session.commit()

    # Test Fetch (without lock)
    query = select(UserCreditBalance).where(UserCreditBalance.user_id == test_user_id)
    result = await repo.session.execute(query)
    balance = result.scalar_one_or_none()
    
    assert balance is not None
    assert balance.subscription_credits == Decimal("100.0000")
    assert balance.purchased_credits == Decimal("50.0000")

@pytest.mark.asyncio
async def test_lock_user_balance_for_update(repo: SubscriptionRepo, test_user_id: uuid.UUID):
    # Setup
    balance_data = {
        "user_id": test_user_id,
        "subscription_credits": Decimal("100.0"),
        "purchased_credits": Decimal("50.0")
    }
    await repo.create_user_credit_balance(balance_data)
    await repo.session.commit()

    # Lock
    locked_balance = await repo.lock_user_balance_for_update(test_user_id)
    assert locked_balance is not None
    assert locked_balance.subscription_credits == Decimal("100.0000")
    
    # In a real environment, another transaction would block here.
    # We just ensure it runs and returns the record properly.

@pytest.mark.asyncio
async def test_update_user_credit_balances(repo: SubscriptionRepo, test_user_id: uuid.UUID):
    # Setup
    await repo.create_user_credit_balance({
        "user_id": test_user_id,
        "subscription_credits": Decimal("100.0"),
        "purchased_credits": Decimal("50.0")
    })
    await repo.session.commit()

    # Update
    await repo.update_user_credit_balances(
        user_id=test_user_id,
        new_sub_balance=Decimal("90.0"),
        new_purchased_balance=Decimal("40.0")
    )
    await repo.session.commit()

    # Verify
    query = select(UserCreditBalance).where(UserCreditBalance.user_id == test_user_id)
    result = await repo.session.execute(query)
    balance = result.scalar_one_or_none()
    
    assert balance.subscription_credits == Decimal("90.0000")
    assert balance.purchased_credits == Decimal("40.0000")

@pytest.mark.asyncio
async def test_insert_usage_ledger(repo: SubscriptionRepo, test_user_id: uuid.UUID):
    ledger_data = UsageLedgerCreate(
        id=uuid.uuid4(),
        user_id=test_user_id,
        session_id=uuid.uuid4(),
        message_id=uuid.uuid4(),
        sub_credits_deducted=Decimal("10.0"),
        purchased_credits_deducted=Decimal("2.0"),
        sub_balanced_after=Decimal("90.0"),
        purchased_balanced_after=Decimal("48.0"),
        created_at=datetime.now(timezone.utc)
    )

    await repo.insert_usage_ledger(ledger_data)
    await repo.session.commit()

    # Verify
    query = select(UsageLedger).where(UsageLedger.user_id == test_user_id)
    result = await repo.session.execute(query)
    ledger = result.scalars().first()
    
    assert ledger is not None
    assert ledger.sub_credits_deducted == Decimal("10.0000")
    assert ledger.purchased_credits_deducted == Decimal("2.0000")

@pytest.mark.asyncio
async def test_create_and_update_user_subscriptions(repo: SubscriptionRepo, test_user_id: uuid.UUID):
    now_utc = datetime.now(timezone.utc)
    subscription_data = {
        "id": uuid.uuid4(),
        "user_id": test_user_id,
        "subscription_tier": "free",
        "current_period_start": now_utc,
        "current_period_end": now_utc + timedelta(days=30),
        "auto_renew": False,
        "status": "active",
        "stripe_subscription_id": "sub_test123"
    }

    # Create
    await repo.create_user_subscription(subscription_data)
    await repo.session.commit()

    # Wait to ensure time difference? No need, just update
    update_payload = UserSubscriptionUpdate(
        subscription_tier="pro",
        status="active",
        auto_renew=True
    )
    
    await repo.update_user_subscriptions(test_user_id, update_payload)
    await repo.session.commit()

    # Verify
    query = select(UserSubscriptions).where(UserSubscriptions.user_id == test_user_id)
    result = await repo.session.execute(query)
    sub = result.scalar_one_or_none()
    
    assert sub is not None
    assert sub.subscription_tier == "pro"
    assert sub.auto_renew is True
    assert sub.status == "active"
