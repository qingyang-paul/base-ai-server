import pytest
from pydantic import ValidationError
from app.auth_service.core.model import (
    BaseTokenPayload, 
    AccessTokenPayload, 
    RefreshTokenPayload, 
    MagicLinkPayload
)

def test_base_token_payload():
    payload = BaseTokenPayload(
        sub="user123", 
        exp=1700000000, 
        jti="unique-id", 
        token_version=1, 
        role="user"
    )
    assert payload.iss == "auth_service"
    assert payload.iat is not None

def test_access_token_payload():
    payload = AccessTokenPayload(
        sub="user123", 
        exp=1700000000, 
        jti="unique-id", 
        token_version=1, 
        role="user"
    )
    assert payload.type == "access"

def test_refresh_token_payload_valid():
    payload = RefreshTokenPayload(
        sub="user123", 
        exp=1700000000, 
        jti="unique-id", 
        token_version=1, 
        role="user",
        family_id="fam-123"
    )
    assert payload.type == "refresh"
    assert payload.family_id == "fam-123"

def test_refresh_token_payload_missing_family_id():
    with pytest.raises(ValidationError):
        RefreshTokenPayload(
            sub="user123", 
            exp=1700000000, 
            jti="unique-id", 
            token_version=1, 
            role="user"
        )

def test_magic_link_payload_valid():
    payload = MagicLinkPayload(
        sub="user123", 
        exp=1700000000, 
        jti="unique-id", 
        token_version=1, 
        role="user",
        type="password_reset",
        email="user@example.com"
    )
    assert payload.type == "password_reset"
    assert payload.email == "user@example.com"

def test_magic_link_payload_invalid_type():
    with pytest.raises(ValidationError):
        MagicLinkPayload(
            sub="user123", 
            exp=1700000000, 
            jti="unique-id", 
            token_version=1, 
            role="user",
            type="invalid_type", 
            email="user@example.com"
        )
