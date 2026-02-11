import os
import pytest
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

# Generate keys at module level so they are available when Settings is instantiated
# during test collection/import

# Generate a dummy Fernet key
fernet_key = Fernet.generate_key().decode()

# Generate dummy RSA keys
private_key = rsa.generate_private_key(
    public_exponent=65537,
    key_size=2048,
)
private_pem = private_key.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption()
).decode()

public_key = private_key.public_key()
public_pem = public_key.public_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PublicFormat.SubjectPublicKeyInfo
).decode()

# Set environment variables immediately
os.environ["JWT_PRIVATE_KEY"] = private_pem
os.environ["JWT_PUBLIC_KEY"] = public_pem
os.environ["SECURITY_ENCRYPTION_KEY"] = fernet_key
# Set defaults if not present
if "ACCESS_TOKEN_EXPIRE_MINUTES" not in os.environ:
    os.environ["ACCESS_TOKEN_EXPIRE_MINUTES"] = "30"
if "REFRESH_TOKEN_EXPIRE_DAYS" not in os.environ:
    os.environ["REFRESH_TOKEN_EXPIRE_DAYS"] = "7"

os.environ["SECURITY_PASSWORD_HASH_ROUNDS"] = "4" # Override for speed

@pytest.fixture(scope="session", autouse=True)
def set_test_env():
    """
    Fixture to ensure env vars are set (redundant but good for documentation)
    """
    pass
