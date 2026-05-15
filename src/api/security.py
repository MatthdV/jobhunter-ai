"""Security helpers — JWT, password hashing, Fernet credential encryption."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from cryptography.fernet import Fernet, InvalidToken
from jose import JWTError, jwt
from passlib.context import CryptContext

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    """Return bcrypt hash of *plain*."""
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Return True if *plain* matches *hashed*."""
    return _pwd_context.verify(plain, hashed)


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------

_ALGORITHM = "HS256"
_ACCESS_TOKEN_EXPIRE_HOURS = 24


def create_access_token(user_id: int, secret: str) -> str:
    """Return a signed JWT with ``sub=str(user_id)``, valid for 24 hours."""
    expire = datetime.now(timezone.utc) + timedelta(hours=_ACCESS_TOKEN_EXPIRE_HOURS)
    payload = {"sub": str(user_id), "exp": expire}
    return jwt.encode(payload, secret, algorithm=_ALGORITHM)


def decode_access_token(token: str, secret: str) -> int | None:
    """Decode *token* and return user_id, or None on any failure."""
    try:
        payload = jwt.decode(token, secret, algorithms=[_ALGORITHM])
        sub = payload.get("sub")
        if sub is None:
            return None
        return int(sub)
    except (JWTError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Fernet credential encryption
# ---------------------------------------------------------------------------


def encrypt_keys(data: dict, fernet_key: str) -> str:
    """Encrypt *data* dict to a Fernet-encrypted base64 string.

    Args:
        data: Credential dict, e.g. ``{"anthropic_api_key": "sk-...", ...}``
        fernet_key: URL-safe base64 Fernet key (from settings.fernet_key).

    Returns:
        Encrypted string safe to store in DB.
    """
    f = Fernet(fernet_key.encode())
    plaintext = json.dumps(data).encode()
    return f.encrypt(plaintext).decode()


def decrypt_keys(blob: str, fernet_key: str) -> dict:
    """Decrypt *blob* back to a credential dict.

    Returns empty dict on any decryption failure (key rotation, corruption).
    """
    try:
        f = Fernet(fernet_key.encode())
        plaintext = f.decrypt(blob.encode())
        return json.loads(plaintext)
    except (InvalidToken, ValueError, json.JSONDecodeError) as exc:
        logger.warning("Failed to decrypt user credentials: %s", exc)
        return {}
