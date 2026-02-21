import pytest
from unittest.mock import AsyncMock, patch
from decimal import Decimal
from uuid import uuid4
from datetime import datetime, timezone

from app.subscription_service.subscription_repo import SubscriptionRepo
from app.subscription_service.subscription_service import SubscriptionService


@pytest.fixture
def mock_repo():
    repo = AsyncMock(spec=SubscriptionRepo)
    # Provide a mock session that also has mock transaction methods if needed
    repo.session = AsyncMock()
    return repo


@pytest.fixture
def subscription_service(mock_repo):
    return SubscriptionService(repo=mock_repo)

