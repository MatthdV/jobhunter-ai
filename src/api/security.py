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
# Password reset tokens (short-lived, scoped via "type" claim)
# ---------------------------------------------------------------------------

_RESET_TOKEN_EXPIRE_MINUTES = 30


def create_reset_token(user_id: int, secret: str) -> str:
    """Return a signed JWT for password reset, valid 30 minutes.

    Carries ``type=reset`` so an access token can't be reused as a reset token
    and vice versa.
    """
    expire = datetime.now(timezone.utc) + timedelta(minutes=_RESET_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": str(user_id), "type": "reset", "exp": expire}
    return jwt.encode(payload, secret, algorithm=_ALGORITHM)


def decode_reset_token(token: str, secret: str) -> int | None:
    """Decode a reset token and return user_id, or None if invalid/expired/wrong type."""
    try:
        payload = jwt.decode(token, secret, algorithms=[_ALGORITHM])
        if payload.get("type") != "reset":
            return None
        sub = payload.get("sub")
        if sub is None:
            return None
        return int(sub)
    except (JWTError, ValueError):
        return None


# ---------------------------------------------------------------------------
# OAuth state tokens (CSRF protection for the Gmail connect flow)
# ---------------------------------------------------------------------------

_OAUTH_STATE_EXPIRE_MINUTES = 10


def create_oauth_state_token(user_id: int, secret: str) -> str:
    """Return a signed JWT used as the OAuth `state` parameter, valid 10 minutes.

    Carries ``type=gmail_oauth`` so access/reset tokens can't be replayed as
    an OAuth state and vice versa.
    """
    expire = datetime.now(timezone.utc) + timedelta(minutes=_OAUTH_STATE_EXPIRE_MINUTES)
    payload = {"sub": str(user_id), "type": "gmail_oauth", "exp": expire}
    return jwt.encode(payload, secret, algorithm=_ALGORITHM)


def decode_oauth_state_token(token: str, secret: str) -> int | None:
    """Decode an OAuth state token and return user_id, or None if invalid/expired/wrong type."""
    try:
        payload = jwt.decode(token, secret, algorithms=[_ALGORITHM])
        if payload.get("type") != "gmail_oauth":
            return None
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
