import pytest
from decimal import Decimal
from uuid import uuid4
from datetime import datetime, timezone

from app.subscription_service.subscription_service import SubscriptionService, SessionMessage
from app.subscription_service.core.exceptions import (
    ModelNotFoundError,
    UserBalanceNotFoundError,
    InsufficientCreditsError,
    ConfigurationError,
)
from app.subscription_service.core.model import UserCreditBalance

def test_calculate_deduction_split(subscription_service):
    # Scenario 1: Sub credits sufficient
    res = subscription_service.calculate_deduction_split(
        required_credits=Decimal("5.0"),
        current_sub_credits=Decimal("10.0"),
        current_purchased_credits=Decimal("2.0")
    )
    assert res["sub_deducted"] == Decimal("5.0")
    assert res["purchased_deducted"] == Decimal("0")
    assert res["is_sufficient"] is True

    # Scenario 2: Sub credits partial, purchased sufficient
    res = subscription_service.calculate_deduction_split(
        required_credits=Decimal("15.0"),
        current_sub_credits=Decimal("10.0"),
        current_purchased_credits=Decimal("10.0")
    )
    assert res["sub_deducted"] == Decimal("10.0")
    assert res["purchased_deducted"] == Decimal("5.0")
    assert res["is_sufficient"] is True
    
    # Scenario 3: Insufficient total credits
    res = subscription_service.calculate_deduction_split(
        required_credits=Decimal("25.0"),
        current_sub_credits=Decimal("10.0"),
        current_purchased_credits=Decimal("10.0")
    )
    assert res["sub_deducted"] == Decimal("0")
    assert res["purchased_deducted"] == Decimal("0")
    assert res["is_sufficient"] is False
    assert res["shortfall"] == Decimal("5.0")


def test_calculate_cost_from_tokens(subscription_service):
    message = SessionMessage(
        user_id=uuid4(),
        session_id=uuid4(),
        message_id=uuid4(),
        model_id="gpt-4-turbo",
        input_tokens=100,
        output_tokens=100
    )
    cost = subscription_service._calculate_cost_from_tokens(message)
    # base_prompt: 0.01, base_completion: 0.03 -> Total cost 1 + 3 = 4
    assert cost == Decimal("4.0")

    message.model_id = "unknown-model"
    with pytest.raises(ModelNotFoundError):
        subscription_service._calculate_cost_from_tokens(message)


@pytest.mark.asyncio
async def test_process_message_billing_success(subscription_service, mock_repo):
    user_id = uuid4()
    message = SessionMessage(
        user_id=user_id,
        session_id=uuid4(),
        message_id=uuid4(),
        model_id="gpt-4-turbo",
        input_tokens=100,
        output_tokens=100
    )
    # Require 4.0 credits
    mock_balance = UserCreditBalance(
        user_id=user_id,
        subscription_credits=Decimal("10.0"),
        purchased_credits=Decimal("0.0"),
        updated_at=datetime.now(timezone.utc)
    )
    mock_repo.lock_user_balance_for_update.return_value = mock_balance

    ledger = await subscription_service.process_message_billing(message)

    assert ledger.sub_credits_deducted == Decimal("4.0")
    assert ledger.purchased_credits_deducted == Decimal("0")
    assert ledger.sub_balanced_after == Decimal("6.0")
    
    mock_repo.lock_user_balance_for_update.assert_called_once_with(user_id)
    mock_repo.insert_usage_ledger.assert_called_once()
    mock_repo.session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_process_message_billing_insufficient_funds(subscription_service, mock_repo):
    user_id = uuid4()
    message = SessionMessage(
        user_id=user_id,
        session_id=uuid4(),
        message_id=uuid4(),
        model_id="gpt-4-turbo",
        input_tokens=100,
        output_tokens=100
    )
    
    mock_balance = UserCreditBalance(
        user_id=user_id,
        subscription_credits=Decimal("1.0"),
        purchased_credits=Decimal("1.0"),
        updated_at=datetime.now(timezone.utc)
    )
    mock_repo.lock_user_balance_for_update.return_value = mock_balance

    with pytest.raises(InsufficientCreditsError):
        await subscription_service.process_message_billing(message)

    mock_repo.session.rollback.assert_called_once()
    mock_repo.session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_handle_user_registration(subscription_service, mock_repo):
    user_id = uuid4()
    await subscription_service.handle_user_registration(user_id)

    mock_repo.create_user_subscription.assert_called_once()
    mock_repo.create_user_credit_balance.assert_called_once()
    mock_repo.session.commit.assert_called_once()

