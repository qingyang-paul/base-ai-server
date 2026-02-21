from fastapi import HTTPException, status

class SubscriptionException(HTTPException):
    """Base exception for subscription service"""
    def __init__(self, status_code: int, detail: str):
        super().__init__(status_code=status_code, detail=detail)

class ModelNotFoundError(SubscriptionException):
    """Raised when the requested model is not found in the registry"""
    def __init__(self, detail: str = "Requested model not found."):
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=detail
        )

class UserBalanceNotFoundError(SubscriptionException):
    """Raised when a user's credit balance record cannot be found"""
    def __init__(self, detail: str = "User credit balance not found."):
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=detail
        )

class InsufficientCreditsError(SubscriptionException):
    """Raised when a user does not have enough credits for an operation"""
    def __init__(self, detail: str = "Insufficient credits for this operation."):
        super().__init__(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=detail
        )

class ConfigurationError(SubscriptionException):
    """Raised when there is a system configuration error"""
    def __init__(self, detail: str = "System configuration error."):
        super().__init__(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=detail
        )
