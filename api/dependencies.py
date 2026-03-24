"""FastAPI shared dependencies."""
from collections.abc import Generator

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from api.auth.service import decode_jwt
from src.config.settings import settings
from src.storage.database import get_session
from src.storage.models import User

_bearer = HTTPBearer()


def get_db() -> Generator[Session, None, None]:
    with get_session() as session:
        yield session


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    if not settings.is_jwt_configured:
        raise HTTPException(status_code=500, detail="JWT not configured")
    try:
        payload = decode_jwt(credentials.credentials, settings.jwt_secret)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    user = db.query(User).filter(User.id == int(payload["sub"])).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def get_llm_client(user: User = Depends(get_current_user)) -> object:
    from api.auth.service import decrypt_api_key
    from src.llm.factory import get_client

    if not user.encrypted_keys or not settings.fernet_key:
        raise HTTPException(status_code=400, detail="No API key configured")
    key = decrypt_api_key(settings.fernet_key, user.encrypted_keys, user.llm_provider or "anthropic")
    if not key:
        raise HTTPException(status_code=400, detail=f"No key for provider {user.llm_provider}")
    return get_client(user.llm_provider or "anthropic", api_key=key)
