from datetime import datetime, timedelta, timezone
from typing import Any, Union, Dict

from jose import jwt
from passlib.context import CryptContext
from cryptography.fernet import Fernet

from app.auth_service.core.config import settings

# Password Hashing Context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Fernet Encryption Context
fernet = Fernet(settings.SECURITY_ENCRYPTION_KEY)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a plain password against a hashed password.
    """
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """
    Generates a bcrypt hash of the password.
    """
    return pwd_context.hash(password)


def create_token(data: Dict[str, Any], expires_delta: Union[timedelta, None] = None) -> str:
    """
    Creates a JWT token (Access or Refresh).
    """
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        # Default to 15 minutes if not specified, though caller should usually specify
        expire = datetime.now(timezone.utc) + timedelta(minutes=15)
    
    to_encode.update({"exp": expire})
    
    encoded_jwt = jwt.encode(
        to_encode, 
        settings.JWT_PRIVATE_KEY, 
        algorithm=settings.JWT_ALGORITHM
    )
    return encoded_jwt


def decode_token(token: str) -> Dict[str, Any]:
    """
    Decodes and verifies a JWT token.
    """
    payload = jwt.decode(
        token, 
        settings.JWT_PUBLIC_KEY, 
        algorithms=[settings.JWT_ALGORITHM]
    )
    return payload


def encrypt_secret(data: str) -> str:
    """
    Encrypts sensitive string data (e.g., TOTP secret) using Fernet.
    Returns a URL-safe base64-encoded string.
    """
    return fernet.encrypt(data.encode()).decode()


def decrypt_secret(token: str) -> str:
    """
    Decrypts a Fernet encrypted token back to the original string.
    """
    return fernet.decrypt(token.encode()).decode()
