"""Authentication endpoints."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from api.auth.schemas import LoginRequest, RegisterRequest, TokenResponse
from api.auth.service import create_jwt, hash_password, verify_password
from api.dependencies import get_db
from src.config.settings import ConfigurationError, settings
from src.storage.models import User

router = APIRouter(prefix="/auth", tags=["auth"])


def _require_jwt_secret() -> str:
    if not settings.is_jwt_configured:
        raise ConfigurationError("JWT_SECRET must be set and at least 32 characters long")
    return settings.jwt_secret


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(body: RegisterRequest, db: Session = Depends(get_db)) -> TokenResponse:
    if db.query(User).filter(User.email == body.email).first():
        raise HTTPException(status_code=409, detail="Email already registered")
    user = User(email=body.email, hashed_password=hash_password(body.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_jwt(user_id=user.id, email=user.email, secret=_require_jwt_secret())
    return TokenResponse(access_token=token)


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.query(User).filter(User.email == body.email).first()
    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_jwt(user_id=user.id, email=user.email, secret=_require_jwt_secret())
    return TokenResponse(access_token=token)
