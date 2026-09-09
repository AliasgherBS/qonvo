"""The smaller hardening items (teardown X9).

Four findings, one of which — the pairing QR being reachable by any tenant
member — was closed by the authorization fix (X1) and is covered by
``test_route_authorization.py``. The other three are here.

Each of them is the same shape: something that was inherited rather than
decided, and would therefore change without anybody noticing.
"""

from __future__ import annotations

import datetime as dt

import jwt
import pytest
from app.core import security
from app.core.config import settings
from app.core.security import (
    ARGON2_MEMORY_COST_KIB,
    ARGON2_PARALLELISM,
    ARGON2_TIME_COST,
    TokenError,
    decode_jwt,
    hash_password,
    verify_password,
)
from app.core.signup_guard import is_disposable_email
from app.services.auth import create_access_token


# --- argon2 parameters ----------------------------------------------------------- #
def test_the_work_factor_is_recorded_in_the_hash():
    """Pinned rather than inherited: a library upgrade could otherwise change
    how expensive it is to guess a password, in either direction, with nothing
    in the codebase saying so."""
    digest = hash_password("a perfectly reasonable phrase")

    assert f"m={ARGON2_MEMORY_COST_KIB}" in digest
    assert f"t={ARGON2_TIME_COST}" in digest
    assert f"p={ARGON2_PARALLELISM}" in digest


def test_it_is_argon2id_not_argon2i_or_argon2d():
    """The variant matters: id is the one resistant to both side-channel and
    GPU attacks, and it is the only one anybody should be choosing."""
    assert hash_password("a perfectly reasonable phrase").startswith("$argon2id$")


def test_the_pinned_cost_is_not_weaker_than_what_it_replaced():
    """The mistake the first version of this made.

    OWASP publishes a *minimum* for Argon2id (19 MiB, t=2, p=1), and pinning to
    it looked like the responsible thing. passlib's own default was already
    64 MiB with three passes, so "pinning to the recommendation" would have
    quietly reduced the work factor for every password set afterwards. A floor
    is not a target.
    """
    from passlib.context import CryptContext

    inherited = CryptContext(schemes=["argon2"], deprecated="auto").hash("x")
    params = dict(
        piece.split("=") for piece in inherited.split("$")[3].split(",")
    )

    assert int(params["m"]) <= ARGON2_MEMORY_COST_KIB
    assert int(params["t"]) <= ARGON2_TIME_COST


def test_a_hash_made_with_other_parameters_still_verifies():
    """passlib reads the cost out of the hash, so pinning does not lock anybody
    out of an account whose password was hashed under the old settings."""
    from passlib.context import CryptContext

    weaker = CryptContext(
        schemes=["argon2"], argon2__memory_cost=8192, argon2__time_cost=1
    ).hash("an existing users password")

    assert verify_password("an existing users password", weaker) is True


def test_an_existing_hash_is_not_needlessly_marked_for_rehash():
    """`deprecated="auto"` rehashes on the next login when the cost has moved.
    Since these are pinned to what was already in use, nothing should be
    marked -- if this fails, the pinned values drifted from the inherited ones
    and every user is being rehashed for no reason."""
    from passlib.context import CryptContext

    inherited = CryptContext(schemes=["argon2"], deprecated="auto").hash("x")

    assert security._pwd_context.needs_update(inherited) is False


# --- audience and issuer --------------------------------------------------------- #
def _token(**claims) -> str:
    now = dt.datetime.now(dt.UTC)
    payload = {
        "sub": "owner@theclinic.pk",
        "typ": "access",
        "aud": settings.jwt_audience,
        "iss": settings.jwt_issuer,
        "iat": now,
        "exp": now + dt.timedelta(hours=1),
        **claims,
    }
    return jwt.encode(
        {k: v for k, v in payload.items() if v is not None},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


def test_they_are_set_rather_than_none():
    """Both defaulted to None, which disabled audience verification entirely.
    It is the same missing-claim discipline that produced X7: a claim nobody
    verifies stops being true without anybody noticing."""
    assert settings.jwt_audience
    assert settings.jwt_issuer


def test_a_minted_token_carries_both():
    payload = jwt.decode(
        create_access_token(
            subject="owner@theclinic.pk", tenant_id=None, role="owner", is_qonvo_admin=False
        ),
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
        audience=settings.jwt_audience,
        issuer=settings.jwt_issuer,
    )

    assert payload["aud"] == settings.jwt_audience
    assert payload["iss"] == settings.jwt_issuer


def test_a_token_with_no_audience_is_refused():
    """Required, not merely verified-if-present. PyJWT skips a claim that is
    absent, so without the `require` list a token minted with neither would
    sail through the very check added for them."""
    with pytest.raises(TokenError, match="aud"):
        decode_jwt(_token(aud=None))


def test_a_token_with_no_issuer_is_refused():
    with pytest.raises(TokenError, match="iss"):
        decode_jwt(_token(iss=None))


def test_a_token_for_another_audience_is_refused():
    with pytest.raises(TokenError, match="[Aa]udience"):
        decode_jwt(_token(aud="somebody-elses-api"))


def test_a_token_from_another_issuer_is_refused():
    with pytest.raises(TokenError, match="[Ii]ssuer"):
        decode_jwt(_token(iss="not-us"))


def test_a_correctly_scoped_token_still_works():
    """Over-correcting here locks everybody out."""
    assert decode_jwt(_token()).subject == "owner@theclinic.pk"


def test_the_reset_and_verification_tokens_do_not_carry_an_audience():
    """They are decoded by plain `jwt.decode` with no audience argument, and
    PyJWT raises InvalidAudienceError for a token that *carries* aud when none
    is expected. Adding these claims there would break every reset link and
    every confirmation link."""
    from app.models.tenant import User
    from app.services.auth import create_email_verification_token, create_password_reset_token

    user = User(
        email="owner@theclinic.pk",
        hashed_password="stand-in",
        email_verified=False,
        is_active=True,
    )
    user.id = __import__("uuid").uuid4()

    for token in (create_password_reset_token(user), create_email_verification_token(user)):
        payload = jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
        assert "aud" not in payload


# --- disposable signup domains --------------------------------------------------- #
@pytest.mark.parametrize(
    "email",
    [
        "someone@mailinator.com",
        "someone@MAILINATOR.COM",
        "someone@yopmail.com",
        "someone@guerrillamail.com",
        "someone@10minutemail.com",
    ],
)
def test_a_throwaway_address_is_refused(email):
    assert is_disposable_email(email) is True


def test_a_subdomain_of_a_throwaway_provider_is_caught():
    """Those providers hand out unlimited subdomains, so listing them
    individually is not possible."""
    assert is_disposable_email("someone@anything.mailinator.com") is True


@pytest.mark.parametrize(
    "email",
    [
        "owner@gmail.com",
        "owner@qonvo.org",
        "owner@theclinic.pk",
        "owner@notmailinator.com",  # merely contains the name
        "owner@sub.gmail.com",
    ],
)
def test_a_real_address_is_allowed(email):
    """The failure mode that matters. An over-broad list rejects paying
    customers, which is why this is a short blocklist rather than one of the
    forty-thousand-entry public lists that go stale weekly."""
    assert is_disposable_email(email) is False


@pytest.mark.parametrize("email", [None, "", "not-an-email", "@", "trailing@"])
def test_malformed_input_does_not_raise(email):
    assert is_disposable_email(email) is False


def test_signup_refuses_a_throwaway_address():
    import ast
    import inspect

    from app.api.auth import signup

    tree = ast.parse(inspect.getsource(signup).lstrip())
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            node.value = ast.Constant(value="")

    assert "is_disposable_email" in ast.unparse(tree)


def test_the_list_is_a_constant_not_a_runtime_fetch():
    """A signup path that depends on fetching a file from somebody else either
    fails open, in which case it does nothing, or fails closed, in which case a
    third party's outage stops registrations."""
    import inspect

    from app.core import signup_guard

    source = inspect.getsource(signup_guard)

    assert "httpx" not in source
    assert "requests" not in source
