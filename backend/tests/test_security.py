"""HMAC verification, JWT decode, and Fernet roundtrip (DESIGN.md §5.1, §8, §3)."""

from __future__ import annotations

import time
from uuid import uuid4

import jwt
import pytest
from app.core.config import settings
from app.core.security import (
    ACCESS_TOKEN_TYPE,
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
    # `typ`, `aud` and `iss` are all part of what makes a token an access
    # token, so the helper mints them by default. Pass any of them as None to
    # build a token without, which is what the rejection tests below need.
    payload = {
        "sub": "user-1",
        "exp": int(time.time()) + 300,
        "typ": ACCESS_TOKEN_TYPE,
        "aud": settings.jwt_audience,
        "iss": settings.jwt_issuer,
        **claims,
    }
    payload = {k: v for k, v in payload.items() if v is not None or k != "typ"}
    if claims.get("typ", "unset") is None:
        payload.pop("typ", None)
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


# --- the token type (X7) --------------------------------------------------------- #
# Every credential in this system is signed with the same secret and algorithm,
# so the only thing distinguishing a password-reset link from a bearer token is
# a claim. decode_jwt used to check neither: it required exp and sub, both of
# which a reset token carries, and the request failed only because
# require_tenant found no tenant_id and answered 403.
#
# That is an accident of the payload, not a decision. Add a tenant id to the
# reset token, to greet the user by business name on the reset page say, and
# every reset email becomes a thirty-minute full-access credential in a URL.
def test_a_token_with_no_type_is_rejected():
    with pytest.raises(TokenError):
        decode_jwt(_make_token(typ=None, tenant_id=str(uuid4()), role="owner"))


def test_a_password_reset_token_cannot_authenticate_a_request():
    """The hazard X7 described, closed. Built the way create_password_reset_token
    builds one, plus the tenant_id that would make it dangerous."""
    from app.services.auth import _password_fingerprint  # noqa: PLC0415

    reset_like = _make_token(
        typ="pwreset",
        pwf="deadbeef",
        # The field whose absence was the only thing saving us.
        tenant_id=str(uuid4()),
        role="owner",
    )
    with pytest.raises(TokenError) as err:
        decode_jwt(reset_like)

    assert "pwreset" in str(err.value)
    assert _password_fingerprint is not None  # the real minter still exists


def test_a_real_access_token_still_decodes():
    """The guard has to reject the other kinds without rejecting the right one."""
    from app.services.auth import create_access_token  # noqa: PLC0415

    tid = uuid4()
    claims = decode_jwt(
        create_access_token(subject="o@t", tenant_id=tid, role="owner", is_qonvo_admin=False)
    )
    assert claims.tenant_id == tid
    assert claims.role == "owner"
