from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
    # JWT Configuration
    JWT_PRIVATE_KEY: str = Field(..., description="Private Key for signing JWTs")
    JWT_PUBLIC_KEY: str = Field(..., description="Public Key for verifying JWTs")
    JWT_ALGORITHM: str = "RS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Password Hashing
    SECURITY_PASSWORD_HASH_ROUNDS: int = 12

    # Encryption (Fernet)
    # Must be 32 url-safe base64-encoded bytes
    SECURITY_ENCRYPTION_KEY: str = Field(..., description="Key for encrypting sensitive data")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore"
    )

settings = Settings()
