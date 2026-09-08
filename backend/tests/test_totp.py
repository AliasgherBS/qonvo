"""The admin's second factor (teardown X4).

``POST /api/admin/tenants/{id}/impersonate`` mints an owner-scoped token for
any tenant on the platform. That is a reasonable support tool and it was
audited. What guarded it was one password on one account, reachable from the
public internet, with no second factor and no separate login surface. One
phished password is every customer's WhatsApp inbox, and the same account can
delete any tenant outright.

The implementation is hand-rolled, following the call already made for the
Prometheus endpoint, and **the RFC's own test vectors are why that is
defensible**: a wrong implementation disagrees with published numbers rather
than merely with an authenticator app somebody has to hold. Those vectors are
the first test below.

The rest are about the ways a second factor locks out the wrong person:
enabling before a code has been proved, refusing a code that was correct when
it was read, and losing the account when the encryption key moves.
"""

from __future__ import annotations

import base64
import time

import pytest
from app.core.totp import (
    DIGITS,
    STEP_SECONDS,
    generate_secret,
    provisioning_uri,
    totp_at,
    verify_code,
)

#: RFC 6238 Appendix B uses the ASCII secret "12345678901234567890" with SHA-1.
RFC_SECRET = base64.b32encode(b"12345678901234567890").decode()


# --- the algorithm is right ------------------------------------------------------ #
@pytest.mark.parametrize(
    "timestamp,expected",
    [
        (59, "94287082"),
        (1111111109, "07081804"),
        (1111111111, "14050471"),
        (1234567890, "89005924"),
        (2000000000, "69279037"),
        (20000000000, "65353130"),
    ],
)
def test_the_rfc_6238_test_vectors(timestamp, expected):
    """The reason hand-rolling this is defensible. Eight digits because that is
    what the RFC's table uses; production uses six."""
    assert totp_at(RFC_SECRET, timestamp=timestamp, digits=8) == expected


def test_production_uses_the_parameters_every_app_assumes():
    """A server that chooses differently produces codes the user's app cannot
    generate, and the user has no way to discover why."""
    assert DIGITS == 6
    assert STEP_SECONDS == 30


def test_a_generated_secret_is_the_right_size_and_shape():
    secret = generate_secret()

    assert len(base64.b32decode(secret + "=" * (-len(secret) % 8))) == 20
    assert secret.isalnum() and secret.isupper()


def test_two_secrets_differ():
    assert generate_secret() != generate_secret()


# --- verification ---------------------------------------------------------------- #
def test_the_current_code_verifies():
    secret = generate_secret()
    now = int(time.time())

    assert verify_code(secret, totp_at(secret, timestamp=now), at=now) is True


def test_the_previous_code_still_verifies():
    """Phone clocks drift and people finish typing after the code rolls over.
    Zero tolerance produces "wrong code" for a code that was right when it was
    read, which is the most common way a second factor becomes a support
    ticket."""
    secret = generate_secret()
    now = int(time.time())

    previous = totp_at(secret, timestamp=now - STEP_SECONDS)

    assert verify_code(secret, previous, at=now) is True


def test_a_code_from_five_minutes_ago_does_not_verify():
    """Tolerance either side is one step. Wider starts widening the guessing
    window for no usability gain."""
    secret = generate_secret()
    now = int(time.time())

    assert verify_code(secret, totp_at(secret, timestamp=now - 300), at=now) is False


def test_another_secrets_code_does_not_verify():
    a, b = generate_secret(), generate_secret()
    now = int(time.time())

    assert verify_code(a, totp_at(b, timestamp=now), at=now) is False


@pytest.mark.parametrize("code", [None, "", "12345", "1234567", "abcdef", "   "])
def test_a_malformed_code_is_refused_without_raising(code):
    assert verify_code(generate_secret(), code) is False


def test_spaces_in_a_typed_code_are_tolerated():
    """Apps display codes as "123 456" and people paste them that way."""
    secret = generate_secret()
    now = int(time.time())
    code = totp_at(secret, timestamp=now)

    assert verify_code(secret, f"{code[:3]} {code[3:]}", at=now) is True


def test_a_hand_retyped_secret_still_works():
    """Apps show secrets without padding, and people retype them in lower case
    with spaces every four characters."""
    secret = generate_secret()
    now = int(time.time())
    messy = " ".join(secret[i : i + 4] for i in range(0, len(secret), 4)).lower()

    assert verify_code(messy, totp_at(secret, timestamp=now), at=now) is True


def test_an_empty_secret_never_verifies():
    """Belt to the braces of `totp_enabled`: a row with the flag set and no
    secret must not accept anything."""
    assert verify_code("", "123456") is False


# --- the provisioning URI -------------------------------------------------------- #
def test_the_uri_is_scannable():
    uri = provisioning_uri("ABCDEFGH", account="admin@qonvo.org")

    assert uri.startswith("otpauth://totp/")
    assert "secret=ABCDEFGH" in uri
    assert "period=30" in uri and "digits=6" in uri


def test_the_label_is_escaped():
    """An unescaped colon or space makes some apps parse the wrong account name
    and others reject the URI outright."""
    uri = provisioning_uri("ABCDEFGH", account="a b@qonvo.org", issuer="Qonvo Support")

    assert " " not in uri
    assert uri.count(":") == 1  # only the scheme's


# --- the service layer ----------------------------------------------------------- #
def make_user(*, enabled: bool, secret: str | None):
    from app.core.security import encrypt_secret
    from app.models.tenant import User

    return User(
        email="admin@qonvo.org",
        hashed_password="stand-in",
        email_verified=True,
        is_active=True,
        totp_enabled=enabled,
        totp_secret=encrypt_secret(secret) if secret else None,
    )


def test_a_user_without_a_factor_never_passes():
    from app.services.auth import verify_totp_for

    secret = generate_secret()
    code = totp_at(secret, timestamp=int(time.time()))

    assert verify_totp_for(make_user(enabled=False, secret=secret), code) is False


def test_an_enabled_user_with_no_secret_never_passes():
    from app.services.auth import verify_totp_for

    assert verify_totp_for(make_user(enabled=True, secret=None), "123456") is False


def test_an_enrolled_user_passes_with_their_code():
    from app.services.auth import verify_totp_for

    secret = generate_secret()
    user = make_user(enabled=True, secret=secret)

    assert verify_totp_for(user, totp_at(secret, timestamp=int(time.time()))) is True


def test_an_undecryptable_secret_fails_closed(monkeypatch):
    """The Fernet key having moved without re-encryption is a mistake, and the
    honest answer to "is this code valid" is then no. Returning True would turn
    a key mistake into an authentication bypass."""
    from app.services import auth as auth_service

    def broken(_value):
        from app.core.security import TokenError

        raise TokenError("key moved")

    monkeypatch.setattr(auth_service, "decrypt_secret", broken)

    user = make_user(enabled=True, secret=generate_secret())

    assert auth_service.verify_totp_for(user, "123456") is False


# --- replay ---------------------------------------------------------------------- #
class FakeRedis:
    def __init__(self, *, broken: bool = False) -> None:
        self.values: dict[str, str] = {}
        self.broken = broken

    async def set(self, key, value, ex=None, nx=False):
        if self.broken:
            raise ConnectionError("redis is down")
        if nx and key in self.values:
            return None
        self.values[key] = value
        return True


async def test_a_code_cannot_be_used_twice():
    """A code stays valid for its window, so without this a code read over
    somebody's shoulder works again within the same minute."""
    from app.services.auth import totp_code_replayed

    redis = FakeRedis()

    assert await totp_code_replayed(redis, "admin@qonvo.org", "123456") is False
    assert await totp_code_replayed(redis, "admin@qonvo.org", "123456") is True


async def test_two_accounts_do_not_share_a_code_namespace():
    from app.services.auth import totp_code_replayed

    redis = FakeRedis()
    await totp_code_replayed(redis, "one@qonvo.org", "123456")

    assert await totp_code_replayed(redis, "two@qonvo.org", "123456") is False


async def test_the_address_is_not_the_key():
    from app.services.auth import totp_code_replayed

    redis = FakeRedis()
    await totp_code_replayed(redis, "Admin@Qonvo.org", "123456")

    [key] = list(redis.values)
    assert "admin" not in key.lower()
    assert "qonvo.org" not in key


async def test_the_replay_check_fails_closed():
    """The opposite of the revocation check's trade, and for the opposite
    reason. Failing open there locks everybody out of a working product;
    failing open here removes the protection at the moment somebody might be
    attacking. The cost of being wrong is one refused login, and there is
    another code in thirty seconds."""
    from app.services.auth import totp_code_replayed

    assert await totp_code_replayed(FakeRedis(broken=True), "admin@qonvo.org", "123456") is True


# --- enrolment safety ------------------------------------------------------------ #
def test_starting_enrolment_does_not_enable_it():
    """Enabling on the strength of having issued a secret locks out anybody
    whose app failed to scan it, and they find out when they next sign in."""
    import ast
    import inspect

    from app.api.auth import totp_start

    tree = ast.parse(inspect.getsource(totp_start).lstrip())
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            node.value = ast.Constant(value="")
    body = ast.unparse(tree)

    assert "user.totp_secret = encrypt_secret" in body
    assert "totp_enabled = True" not in body


def test_disabling_requires_a_code():
    """Otherwise a stolen session removes the protection that would have made
    the session hard to steal."""
    import ast
    import inspect

    from app.api.auth import totp_disable

    tree = ast.parse(inspect.getsource(totp_disable).lstrip())
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            node.value = ast.Constant(value="")

    assert "verify_totp_for" in ast.unparse(tree)


def test_the_secret_is_stored_encrypted():
    """It is a credential: whoever holds it generates valid codes forever."""
    secret = generate_secret()
    user = make_user(enabled=True, secret=secret)

    assert user.totp_secret != secret
    assert secret not in (user.totp_secret or "")


def test_login_checks_the_factor_after_the_password():
    """Asking for a code before the password is right tells an attacker which
    addresses have 2FA enabled; asking at all for an account without one tells
    them the opposite."""
    import inspect

    from app.api.auth import login

    source = inspect.getsource(login)

    assert source.index("await authenticate(") < source.index("totp_enabled")


def test_a_wrong_code_counts_against_the_account():
    """A correct password plus unlimited code guesses is a million tries at six
    digits, which the throttle only stops if the failure is recorded."""
    import ast
    import inspect

    from app.api.auth import login

    tree = ast.parse(inspect.getsource(login).lstrip())
    body = ast.unparse(tree)
    after = body[body.index("totp_enabled") :]

    assert "record_failure" in after
