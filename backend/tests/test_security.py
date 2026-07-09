"""HMAC verification, JWT decode, and Fernet roundtrip (DESIGN.md §5.1, §8, §3)."""

from __future__ import annotations

import time
from uuid import uuid4

import jwt
import pytest
from app.core.config import settings
from app.core.security import (
    TokenError,
    compute_waha_hmac,
    decode_jwt,
    decrypt_secret,
    encrypt_secret,
    verify_waha_hmac,
)

RAW_BODY = b'{"event":"message","session":"s1","payload":{"id":"abc"}}'


def test_hmac_valid():
    sig = compute_waha_hmac(RAW_BODY, settings.waha_hmac_secret)
    assert verify_waha_hmac(RAW_BODY, sig, settings.waha_hmac_secret) is True


def test_hmac_invalid_signature():
    assert verify_waha_hmac(RAW_BODY, "deadbeef", settings.waha_hmac_secret) is False


def test_hmac_tampered_body():
    sig = compute_waha_hmac(RAW_BODY, settings.waha_hmac_secret)
    assert verify_waha_hmac(RAW_BODY + b"x", sig, settings.waha_hmac_secret) is False


def test_hmac_missing_signature():
    assert verify_waha_hmac(RAW_BODY, None, settings.waha_hmac_secret) is False
    assert verify_waha_hmac(RAW_BODY, "", settings.waha_hmac_secret) is False


def test_hmac_wrong_secret():
    sig = compute_waha_hmac(RAW_BODY, "other-secret")
    assert verify_waha_hmac(RAW_BODY, sig, settings.waha_hmac_secret) is False


def _make_token(**claims) -> str:
    payload = {"sub": "user-1", "exp": int(time.time()) + 300, **claims}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def test_jwt_decode_with_tenant_and_role():
    tid = uuid4()
    token = _make_token(tenant_id=str(tid), role="owner")
    claims = decode_jwt(token)
    assert claims.tenant_id == tid
    assert claims.role == "owner"
    assert claims.is_qonvo_admin is False


def test_jwt_admin_without_tenant():
    claims = decode_jwt(_make_token(qonvo_admin=True))
    assert claims.tenant_id is None
    assert claims.is_qonvo_admin is True


def test_jwt_expired_rejected():
    token = jwt.encode(
        {"sub": "u", "exp": int(time.time()) - 10},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(TokenError):
        decode_jwt(token)


def test_jwt_bad_signature_rejected():
    token = jwt.encode({"sub": "u", "exp": int(time.time()) + 300}, "wrong", algorithm="HS256")
    with pytest.raises(TokenError):
        decode_jwt(token)


def test_fernet_roundtrip():
    ciphertext = encrypt_secret("super-secret-token")
    assert ciphertext != "super-secret-token"
    assert decrypt_secret(ciphertext) == "super-secret-token"


def test_fernet_bad_token_raises():
    with pytest.raises(TokenError):
        decrypt_secret("not-a-valid-fernet-token")
