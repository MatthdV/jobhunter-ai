"""Unit tests for auth crypto primitives — no DB needed."""
import pytest
from api.auth.service import (
    create_jwt,
    decode_jwt,
    decrypt_api_key,
    encrypt_api_key,
    hash_password,
    verify_password,
)

SECRET = "test-secret-at-least-32-characters-long"


def test_hash_and_verify_password():
    hashed = hash_password("mysecret")
    assert hashed != "mysecret"
    assert verify_password("mysecret", hashed)
    assert not verify_password("wrong", hashed)


def test_create_and_decode_jwt():
    token = create_jwt(user_id=1, email="a@b.com", secret=SECRET)
    payload = decode_jwt(token, SECRET)
    assert payload["sub"] == "1"
    assert payload["email"] == "a@b.com"


def test_decode_jwt_invalid_raises():
    with pytest.raises(Exception):
        decode_jwt("bad.token.here", SECRET)


def test_encrypt_decrypt_api_key():
    from cryptography.fernet import Fernet

    key = Fernet.generate_key().decode()
    encrypted = encrypt_api_key(key, "anthropic", "sk-ant-test", existing=None)
    result = decrypt_api_key(key, encrypted, "anthropic")
    assert result == "sk-ant-test"


def test_encrypt_api_key_merges_providers():
    from cryptography.fernet import Fernet

    key = Fernet.generate_key().decode()
    enc1 = encrypt_api_key(key, "anthropic", "sk-ant", existing=None)
    enc2 = encrypt_api_key(key, "openai", "sk-oai", existing=enc1)
    assert decrypt_api_key(key, enc2, "anthropic") == "sk-ant"
    assert decrypt_api_key(key, enc2, "openai") == "sk-oai"


def test_decrypt_missing_provider_returns_empty():
    from cryptography.fernet import Fernet

    key = Fernet.generate_key().decode()
    enc = encrypt_api_key(key, "anthropic", "sk-ant", existing=None)
    assert decrypt_api_key(key, enc, "openai") == ""
