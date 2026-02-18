class ChatServiceError(Exception):
    """Base exception for Chat Service."""
    pass

class ProviderNotFoundError(ChatServiceError):
    """Raised when a requested LLM provider is not found."""
    pass

class ModelConfigError(ChatServiceError):
    """Raised when the runtime configuration is invalid for the provider."""
    pass
