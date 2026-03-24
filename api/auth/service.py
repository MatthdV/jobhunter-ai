"""Cryptographic primitives: password hashing, JWT, Fernet key encryption."""
import json
from datetime import datetime, timedelta, timezone

from cryptography.fernet import Fernet
from jose import jwt
from passlib.context import CryptContext

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 24


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd_context.verify(plain, hashed)


def create_jwt(user_id: int, email: str, secret: str) -> str:
    payload = {
        "sub": str(user_id),
        "email": email,
        "exp": datetime.now(tz=timezone.utc) + timedelta(hours=JWT_EXPIRE_HOURS),
    }
    return jwt.encode(payload, secret, algorithm=JWT_ALGORITHM)


def decode_jwt(token: str, secret: str) -> dict[str, str]:
    return jwt.decode(token, secret, algorithms=[JWT_ALGORITHM])  # type: ignore[no-any-return]


def encrypt_api_key(fernet_key: str, provider: str, api_key: str, existing: str | None) -> str:
    """Encrypt a provider API key and merge with existing encrypted blob."""
    f = Fernet(fernet_key.encode())
    keys: dict[str, str] = {}
    if existing:
        try:
            keys = json.loads(f.decrypt(existing.encode()).decode())
        except Exception:
            keys = {}
    keys[provider] = api_key
    return f.encrypt(json.dumps(keys).encode()).decode()


def decrypt_api_key(fernet_key: str, encrypted: str, provider: str) -> str:
    """Return decrypted API key for provider, or empty string if not found."""
    f = Fernet(fernet_key.encode())
    try:
        keys: dict[str, str] = json.loads(f.decrypt(encrypted.encode()).decode())
        return keys.get(provider, "")
    except Exception:
        return ""
