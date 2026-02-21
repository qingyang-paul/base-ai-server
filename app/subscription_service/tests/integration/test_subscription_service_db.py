import pytest
import pytest_asyncio
import uuid
from decimal import Decimal
from datetime import datetime, timezone

from app.subscription_service.core.model import UserCreditBalance, UserSubscriptions, UsageLedger
from app.subscription_service.core.schema import UsageLedgerCreate
from app.subscription_service.subscription_repo import SubscriptionRepo
from app.subscription_service.subscription_service import SubscriptionService, SessionMessage
from app.subscription_service.core.exceptions import InsufficientCreditsError

@pytest.fixture
def test_user_id() -> uuid.UUID:
    return uuid.uuid4()

@pytest.fixture
def service(repo: SubscriptionRepo) -> SubscriptionService:
    return SubscriptionService(repo=repo)


@pytest.mark.asyncio
async def test_handle_user_registration(service: SubscriptionService, repo: SubscriptionRepo, test_user_id: uuid.UUID):
    await service.handle_user_registration(test_user_id)
    
    # Verify in DB directly
    from sqlalchemy import select
    query_sub = select(UserSubscriptions).where(UserSubscriptions.user_id == test_user_id)
    res_sub = await repo.session.execute(query_sub)
    sub = res_sub.scalar_one_or_none()
    
    assert sub is not None
    assert sub.subscription_tier == "free"

    query_bal = select(UserCreditBalance).where(UserCreditBalance.user_id == test_user_id)
    res_bal = await repo.session.execute(query_bal)
    bal = res_bal.scalar_one_or_none()
    
    assert bal is not None
    assert bal.subscription_credits == Decimal("300.0000") # from PLAN_REGISTRY["free"]


@pytest.mark.asyncio
async def test_process_message_billing_success_db(service: SubscriptionService, repo: SubscriptionRepo, test_user_id: uuid.UUID):
    # Setup Balance first
    await repo.create_user_credit_balance({
        "user_id": test_user_id,
        "subscription_credits": Decimal("10.0"),
        "purchased_credits": Decimal("5.0")
    })
    await repo.session.commit()

    message = SessionMessage(
        user_id=test_user_id,
        session_id=uuid.uuid4(),
        message_id=uuid.uuid4(),
        model_id="gpt-4-turbo",
        input_tokens=100,
        output_tokens=100
    )
    # Required: 4.0

    ledger = await service.process_message_billing(message)

    assert ledger.sub_credits_deducted == Decimal("4.0")
    assert ledger.purchased_credits_deducted == Decimal("0.0")

    # Verify Balance was permanently changed
    from sqlalchemy import select
    query_bal = select(UserCreditBalance).where(UserCreditBalance.user_id == test_user_id)
    res_bal = await repo.session.execute(query_bal)
    bal = res_bal.scalar_one_or_none()
    
    assert bal.subscription_credits == Decimal("6.0000")
    assert bal.purchased_credits == Decimal("5.0000")

    # Verify Ledger was saved
    query_leg = select(UsageLedger).where(UsageLedger.message_id == message.message_id)
    res_leg = await repo.session.execute(query_leg)
    db_ledger = res_leg.scalar_one_or_none()
    
    assert db_ledger is not None
    assert db_ledger.sub_credits_deducted == Decimal("4.0000")


@pytest.mark.asyncio
async def test_process_message_billing_insufficient_rollback(service: SubscriptionService, repo: SubscriptionRepo, test_user_id: uuid.UUID):
    # Setup Balance
    await repo.create_user_credit_balance({
        "user_id": test_user_id,
        "subscription_credits": Decimal("1.0"),
        "purchased_credits": Decimal("1.0")
    })
    await repo.session.commit()

    message = SessionMessage(
        user_id=test_user_id,
        session_id=uuid.uuid4(),
        message_id=uuid.uuid4(),
        model_id="gpt-4-turbo",
        input_tokens=100,
        output_tokens=100
    )
    # Required: 4.0

    with pytest.raises(InsufficientCreditsError):
        await service.process_message_billing(message)

    # Verify Balance is unchanged and transaction rolled back successfully
    from sqlalchemy import select
    query_bal = select(UserCreditBalance).where(UserCreditBalance.user_id == test_user_id)
    res_bal = await repo.session.execute(query_bal)
    bal = res_bal.scalar_one_or_none()
    
    assert bal.subscription_credits == Decimal("1.0000")

    # Verify NO Ledger was created
    query_leg = select(UsageLedger).where(UsageLedger.message_id == message.message_id)
    res_leg = await repo.session.execute(query_leg)
    db_ledger = res_leg.scalar_one_or_none()
    
    assert db_ledger is None
