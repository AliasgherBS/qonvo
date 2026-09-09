"""Email verification, and the pre-hijacking it closes (teardown X2).

There was no verification anywhere in the password path: no token, no mail, no
column. On its own that is untidy. Combined with ``POST /api/auth/google``
resolving the account by looking the Google-verified address up with
``find_user`` and signing into whatever row it finds, it was account
pre-hijacking:

1. The attacker signs up as ``owner@theclinic.pk`` with a password only they
   know. No mail was ever sent, so nobody learns of it.
2. The real owner later clicks Sign in with Google. Google asserts the address,
   the lookup matches the attacker's row, and the owner is signed into the
   attacker's tenant as its owner.
3. They connect their number and upload their price list. The attacker's
   password still works.

Most of what is below is about the token, because the token is what makes the
column trustworthy, and the ways a self-invalidating token goes wrong are quiet
ones: it keeps working after use, or it is interchangeable with a reset token
signed by the same key.
"""

from __future__ import annotations

import datetime as dt
import uuid

import jwt
import pytest
from app.core.config import settings
from app.core.security import TokenError, decode_jwt
from app.models.tenant import User
from app.services import auth as auth_service


def make_user(*, email: str = "owner@theclinic.pk", verified: bool = False) -> User:
    user = User(
        email=email,
        hashed_password="argon2-hash-stands-in",
        full_name="Real Owner",
        email_verified=verified,
        # Set explicitly, because a column default is applied at INSERT rather
        # than at construction: on an unflushed object this is None, and
        # `not None` made the disabled-account test below pass for the wrong
        # reason while the two happy-path tests failed.
        is_active=True,
    )
    # Not flushed, so the ORM has not assigned one. The fingerprint reads it.
    user.id = uuid.uuid4()
    return user


class FakeSession:
    """Enough session for verify_email: it looks a user up and flushes."""

    def __init__(self, user: User | None) -> None:
        self.user = user
        self.flushed = False

    async def flush(self) -> None:
        self.flushed = True


@pytest.fixture
def stub_find_user(monkeypatch):
    """Point find_user at one in-memory user, so these stay unit tests."""

    def install(user: User | None):
        async def fake(db, email):  # noqa: ANN001
            if user is None:
                return None
            return user if user.email == email.lower().strip() else None

        monkeypatch.setattr(auth_service, "find_user", fake)
        return FakeSession(user)

    return install


# --- the token does what a verification token must ------------------------------- #
async def test_a_fresh_token_verifies_the_address(stub_find_user):
    user = make_user()
    db = stub_find_user(user)
    token = auth_service.create_email_verification_token(user)

    verified = await auth_service.verify_email(db, token)

    assert verified is user
    assert user.email_verified is True
    assert db.flushed is True


async def test_the_same_link_cannot_be_used_twice(stub_find_user):
    """The fingerprint is what makes this single-use with no token table to
    clean up. If it stopped covering ``email_verified`` the link would keep
    working forever, and a link that keeps working is one that can be replayed
    out of a mailbox somebody else later reads."""
    user = make_user()
    db = stub_find_user(user)
    token = auth_service.create_email_verification_token(user)

    assert await auth_service.verify_email(db, token) is user
    assert await auth_service.verify_email(db, token) is None


async def test_changing_the_address_invalidates_a_pending_link(stub_find_user):
    """Otherwise a link issued for the old address would verify the new one,
    which is the whole property inverted: the account would end up with a
    confirmed address nobody ever confirmed."""
    user = make_user(email="old@theclinic.pk")
    token = auth_service.create_email_verification_token(user)

    user.email = "new@theclinic.pk"
    db = stub_find_user(user)

    # The subject no longer resolves, and even if it did the fingerprint moved.
    assert await auth_service.verify_email(db, token) is None


async def test_an_expired_link_is_refused(stub_find_user, monkeypatch):
    user = make_user()
    db = stub_find_user(user)
    monkeypatch.setattr(auth_service, "EMAIL_VERIFICATION_TTL_HOURS", -1)
    token = auth_service.create_email_verification_token(user)

    assert await auth_service.verify_email(db, token) is None
    assert user.email_verified is False


async def test_a_disabled_account_cannot_be_verified(stub_find_user):
    user = make_user()
    user.is_active = False
    db = stub_find_user(user)
    token = auth_service.create_email_verification_token(user)

    assert await auth_service.verify_email(db, token) is None


async def test_the_link_is_generous_enough_to_be_opened_later():
    """Thirty minutes, as the reset link has, would mostly generate support
    requests: this one arrives mid-signup and is often opened on a phone after
    the tab is closed. It proves control of a mailbox rather than granting a
    session, so a long window is the right trade."""
    assert auth_service.EMAIL_VERIFICATION_TTL_HOURS >= 12


# --- the token types are not interchangeable ------------------------------------- #
async def test_a_password_reset_token_cannot_verify_an_address(stub_find_user):
    """Both are signed with the same key and carry ``sub`` and ``exp``, so
    ``typ`` is the only thing separating them. A reset token verifying an
    address would let anyone who triggered a forgot-password mail for an
    address they do not own confirm it."""
    user = make_user()
    db = stub_find_user(user)
    reset = auth_service.create_password_reset_token(user)

    assert await auth_service.verify_email(db, reset) is None
    assert user.email_verified is False


def test_a_verification_token_cannot_authenticate_a_request():
    """The other direction, and the one that was actually broken before this
    branch: ``decode_jwt`` required ``typ`` to be present and never compared
    it. A verification token carries no tenant, but it does carry ``sub``."""
    user = make_user()
    token = auth_service.create_email_verification_token(user)

    with pytest.raises(TokenError):
        decode_jwt(token)


def test_a_verification_token_carrying_a_tenant_is_still_refused():
    """The claim, not the shape. A hand-built token with everything an access
    token has except the right ``typ`` must not open a session."""
    now = dt.datetime.now(dt.UTC)
    forged = jwt.encode(
        {
            "sub": "owner@theclinic.pk",
            "typ": "emailverify",
            "tenant_id": str(uuid.uuid4()),
            "role": "owner",
            "iat": now,
            "exp": now + dt.timedelta(hours=1),
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )

    with pytest.raises(TokenError):
        decode_jwt(forged)


# --- signup leaves the address unproven ------------------------------------------ #
def test_a_new_account_is_unverified_by_default():
    """``provision_tenant`` takes the flag explicitly and defaults to the safe
    value. A model default would not be enough: the caller always supplying the
    field is how ``warmup_stage`` ended up never being set."""
    import inspect

    signature = inspect.signature(auth_service.provision_tenant)

    assert signature.parameters["email_verified"].default is False
