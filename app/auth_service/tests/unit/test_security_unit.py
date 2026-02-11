import pytest
from datetime import timedelta
from jose import jwt

# We need to import security AFTER conftest has set env vars
from app.auth_service.core import security
from app.auth_service.core.config import settings

def test_password_hashing():
    password = "secret_password"
    hashed = security.get_password_hash(password)
    assert hashed != password
    assert security.verify_password(password, hashed)
    assert not security.verify_password("wrong_password", hashed)

def test_token_creation_and_decoding():
    data = {"sub": "user123", "role": "admin"}
    token = security.create_token(data)
    
    decoded = security.decode_token(token)
    assert decoded["sub"] == "user123"
    assert decoded["role"] == "admin"
    assert "exp" in decoded

def test_token_expiration():
    data = {"sub": "user_expired"}
    # Create a token that expired 1 minute ago
    expires = timedelta(minutes=-1) 
    token = security.create_token(data, expires_delta=expires)
    
    with pytest.raises(jwt.ExpiredSignatureError):
        security.decode_token(token)

def test_fernet_encryption():
    secret = "my_super_secret_totp"
    encrypted = security.encrypt_secret(secret)
    assert encrypted != secret
    
    decrypted = security.decrypt_secret(encrypted)
    assert decrypted == secret
