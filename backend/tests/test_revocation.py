"""Making a token stop working before it expires (teardown X6).

The access token was a stateless JWT with a 24-hour life, no ``jti`` and no
denylist. So signing out cleared the browser's copy and left the credential
valid; removing a team member took away their membership and left their token
working; suspending a tenant stopped nothing already in somebody's hand; and
changing a password did not end the sessions the old password had opened, which
is the one thing everybody expects a password change to do.

Most of these are about the ways a denylist hurts the wrong person: revoking
one session must not revoke the others, revoking must not reach into the future
and refuse the token somebody was just issued, and an unreachable Redis must
not lock the whole product out.
"""

from __future__ import annotations

import datetime as dt

import pytest
from app.core import revocation
from app.core.security import decode_jwt
from app.services.auth import create_access_token

TENANT = __import__("uuid").uuid4()


class FakeRedis:
    def __init__(self, *, broken: bool = False) -> None:
        self.values: dict[str, str] = {}
        self.expiries: dict[str, int] = {}
        self.broken = broken

    async def set(self, key, value, ex=None):
        if self.broken:
            raise ConnectionError("redis is down")
        self.values[key] = str(value)
        if ex is not None:
            self.expiries[key] = ex

    async def get(self, key):
        if self.broken:
            raise ConnectionError("redis is down")
        value = self.values.get(key)
        return None if value is None else value.encode()


@pytest.fixture
def later(monkeypatch):
    """Move the revocation clock forward, rather than sleeping through it.

    The markers compare a token's `iat` against "now", so these tests need the
    marker to be strictly after the token. Six real sleeps would add seven
    seconds to the suite and make it flaky on a slow machine.
    """

    def advance(seconds: int = 60):
        base = revocation._now()
        monkeypatch.setattr(revocation, "_now", lambda: base + seconds)

    return advance


def token(subject="owner@theclinic.pk", tenant_id=TENANT):
    raw = create_access_token(
        subject=subject, tenant_id=tenant_id, role="owner", is_qonvo_admin=False
    )
    return decode_jwt(raw)


# --- a token carries what revocation needs ---------------------------------------- #
def test_an_access_token_has_a_unique_id():
    """Without a `jti` there is nothing to revoke one session by, which is why
    signing out could only ever clear the browser's own copy."""
    a, b = token(), token()

    assert a.jti and b.jti
    assert a.jti != b.jti


def test_an_access_token_records_when_it_was_issued():
    """The bulk markers compare against `iat`, so a token without one cannot be
    caught by them."""
    assert token().issued_at is not None


# --- one session ------------------------------------------------------------------ #
async def test_revoking_a_token_refuses_it():
    redis = FakeRedis()
    claims = token()

    assert await revocation.is_revoked(redis, claims) is False
    await revocation.revoke_token(redis, jti=claims.jti, expires_at=claims.raw["exp"])
    assert await revocation.is_revoked(redis, claims) is True


async def test_signing_out_on_one_device_leaves_the_others_alone():
    """Otherwise signing out on a laptop signs the same person out on their
    phone, which is not what the button says."""
    redis = FakeRedis()
    laptop, phone = token(), token()

    await revocation.revoke_token(redis, jti=laptop.jti, expires_at=laptop.raw["exp"])

    assert await revocation.is_revoked(redis, laptop) is True
    assert await revocation.is_revoked(redis, phone) is False


async def test_the_denylist_entry_expires_with_the_token():
    """Keeping it longer grows the list forever for no benefit: once `exp` has
    passed, the signature check refuses the token without help."""
    redis = FakeRedis()
    claims = token()

    await revocation.revoke_token(redis, jti=claims.jti, expires_at=claims.raw["exp"])

    [ttl] = list(redis.expiries.values())
    assert 0 < ttl <= 24 * 60 * 60 + 5


async def test_a_token_with_no_jti_is_not_an_error():
    """Tokens minted before the claim existed are still valid for their life
    after a deploy. They cannot be revoked individually, which is what the
    subject-level marker is for."""
    redis = FakeRedis()

    await revocation.revoke_token(redis, jti=None, expires_at=None)

    assert redis.values == {}


# --- every session for somebody --------------------------------------------------- #
async def test_revoking_a_subject_refuses_tokens_it_has_never_seen(later):
    """The shape the other three cases need: removing a member, suspending a
    tenant and changing a password all have to invalidate tokens whose jti we
    have no record of."""
    redis = FakeRedis()
    old = token(subject="leaver@theclinic.pk")
    later()

    await revocation.revoke_all_for_subject(redis, "leaver@theclinic.pk")

    assert await revocation.is_revoked(redis, old) is True


async def test_revoking_a_subject_leaves_everybody_else_alone(later):
    redis = FakeRedis()
    other = token(subject="stays@theclinic.pk")
    later()

    await revocation.revoke_all_for_subject(redis, "leaver@theclinic.pk")

    assert await revocation.is_revoked(redis, other) is False


async def test_a_token_minted_in_the_same_second_as_the_revocation_survives():
    """The one that would be a self-inflicted lockout, and the reason the
    comparison is ``<`` rather than ``<=``.

    A password change revokes everything and then hands back a new session in
    the same request. If the marker caught a token whose ``iat`` equals it, the
    person who just changed their password would be signed out of the session
    they were being given, and signing in again would do the same thing
    forever.
    """
    redis = FakeRedis()
    await revocation.revoke_all_for_subject(redis, "owner@theclinic.pk")

    fresh = token(subject="owner@theclinic.pk")

    assert await revocation.is_revoked(redis, fresh) is False


async def test_a_token_issued_well_after_the_revocation_still_works(later):
    """The ordinary version of the same property, with the clock moved so the
    two timestamps cannot coincide by accident."""
    redis = FakeRedis()
    later(-60)  # the marker is written a minute in the past
    await revocation.revoke_all_for_subject(redis, "owner@theclinic.pk")

    fresh = token(subject="owner@theclinic.pk")

    assert await revocation.is_revoked(redis, fresh) is False


async def test_the_address_is_not_the_redis_key():
    """Redis keys show up in logs, in MONITOR output and to anyone who runs
    KEYS *. Same reasoning as the throttle's."""
    redis = FakeRedis()

    await revocation.revoke_all_for_subject(redis, "Owner@TheClinic.pk")

    [key] = list(redis.values)
    assert "owner" not in key.lower()
    assert "theclinic" not in key.lower()


async def test_the_same_address_hashes_the_same_however_it_is_typed():
    a, b = FakeRedis(), FakeRedis()

    await revocation.revoke_all_for_subject(a, " Owner@TheClinic.pk ")
    await revocation.revoke_all_for_subject(b, "owner@theclinic.pk")

    assert list(a.values) == list(b.values)


async def test_signing_out_everywhere_also_revokes_the_calling_token():
    """The marker only catches tokens issued strictly before it, which is
    deliberate. But this endpoint issues no replacement, so a caller whose
    token shares the marker's second would stay signed in on the device they
    pressed the button on. Caught live at one-second granularity, which is why
    the endpoint uses both mechanisms."""
    import ast
    import inspect

    from app.api import auth as auth_api

    tree = ast.parse(inspect.getsource(auth_api.logout_everywhere).lstrip())
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            node.value = ast.Constant(value="")
    body = ast.unparse(tree)

    assert "revoke_all_for_subject" in body
    assert "revoke_token" in body


# --- every session for a tenant --------------------------------------------------- #
async def test_suspending_a_tenant_refuses_its_tokens(later):
    redis = FakeRedis()
    inside = token(tenant_id=TENANT)
    later()

    await revocation.revoke_all_for_tenant(redis, TENANT)

    assert await revocation.is_revoked(redis, inside) is True


async def test_suspending_one_tenant_does_not_touch_another(later):
    import uuid

    redis = FakeRedis()
    elsewhere = token(tenant_id=uuid.uuid4())
    later()

    await revocation.revoke_all_for_tenant(redis, TENANT)

    assert await revocation.is_revoked(redis, elsewhere) is False


async def test_a_tenantless_admin_token_is_not_caught_by_a_tenant_marker(later):
    """A cross-tenant admin has no tenant_id, and looking up
    `revoked:tenant:None` would be nonsense."""
    redis = FakeRedis()
    admin = token(tenant_id=None)
    later()

    await revocation.revoke_all_for_tenant(redis, TENANT)

    assert await revocation.is_revoked(redis, admin) is False


# --- the outage case -------------------------------------------------------------- #
async def test_it_fails_open_when_redis_is_down():
    """A documented trade rather than an oversight. Refusing every request
    would turn a cache outage into a total outage of a product whose database
    is fine, and the exposure is bounded by the token's own TTL."""
    redis = FakeRedis(broken=True)
    claims = token()

    assert await revocation.is_revoked(redis, claims) is False
    # And the write side must not raise either.
    await revocation.revoke_token(redis, jti=claims.jti, expires_at=claims.raw["exp"])
    await revocation.revoke_all_for_subject(redis, "owner@theclinic.pk")
    await revocation.revoke_all_for_tenant(redis, TENANT)


# --- the endpoints and triggers are actually wired -------------------------------- #
@pytest.mark.parametrize(
    "module,function,call",
    [
        ("app.api.auth", "logout", "revoke_token"),
        ("app.api.auth", "logout_everywhere", "revoke_all_for_subject"),
        ("app.api.auth", "change_password_route", "revoke_all_for_subject"),
        ("app.api.auth", "reset_password_route", "revoke_all_for_subject"),
        ("app.api.team", "remove_member", "revoke_all_for_subject"),
        ("app.api.admin", "update_tenant", "revoke_all_for_tenant"),
    ],
)
def test_the_trigger_is_wired(module, function, call):
    """Each case the teardown named, pinned so a regression names the trigger."""
    import ast
    import inspect

    source = inspect.getsource(getattr(__import__(module, fromlist=["x"]), function))
    tree = ast.parse(source.lstrip())
    # Strip docstrings so prose describing revocation cannot satisfy this.
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            node.value = ast.Constant(value="")

    assert call in ast.unparse(tree)


def test_the_claims_check_runs_on_every_authenticated_request():
    """The check has to live in the one dependency every route goes through,
    not be remembered per route."""
    import ast
    import inspect

    from app.api import deps

    tree = ast.parse(inspect.getsource(deps.get_claims))
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            node.value = ast.Constant(value="")

    assert "is_revoked" in ast.unparse(tree)


def test_the_dashboard_session_does_not_outlive_the_token():
    """Auth.js defaults to thirty days around a token that lasts one, so for
    twenty-nine of them the browser believed it was signed in while every API
    call returned 401."""
    from pathlib import Path

    from app.core.config import settings

    auth_ts = (Path(__file__).resolve().parents[2] / "dashboard" / "auth.ts").read_text()
    expected = f"maxAge: {settings.jwt_expiry_hours} * 60 * 60"

    assert expected in auth_ts, f"expected {expected!r} in dashboard/auth.ts"


def test_a_revoked_token_and_an_invalid_one_answer_the_same():
    """Telling whoever holds a token that it was specifically revoked tells
    them something they do not need to know, and the client's next move is the
    same either way."""
    import ast
    import inspect

    from app.api import deps

    source = inspect.getsource(deps.get_claims)
    tree = ast.parse(source)
    codes = {
        node.value.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.keyword)
        and node.arg == "status_code"
        and isinstance(node.value, ast.Attribute)
    }

    assert codes == {"HTTP_401_UNAUTHORIZED"}


def test_the_expiry_is_measured_in_a_day_not_a_month():
    """Fail-open is only defensible while the token's own life bounds the
    exposure."""
    from app.core.config import settings

    assert settings.jwt_expiry_hours <= 24
    assert settings.jwt_expiry_hours * 3600 < revocation._MARKER_TTL_SECONDS


def test_the_marker_uses_a_real_timestamp():
    """A marker in the past would revoke nothing; one in the future would
    revoke tokens not yet issued."""
    before = int(dt.datetime.now(dt.UTC).timestamp())

    assert before - 2 <= revocation._now() <= before + 2


# --- sessions, and refreshing them ------------------------------------------------ #
async def test_revoking_a_session_kills_every_token_in_its_chain():
    """Why `sid` exists. Revoking a `jti` kills one token, and once a session
    can be refreshed that is one link of a chain: killing the newest link stops
    whoever holds it and leaves anybody who forked the chain -- somebody who
    stole a token and refreshed it -- still inside."""
    redis = FakeRedis()
    first = token()
    # A refresh: same session, new token id.
    refreshed = decode_jwt(
        create_access_token(
            subject="owner@theclinic.pk",
            tenant_id=TENANT,
            role="owner",
            is_qonvo_admin=False,
            session_id=first.session_id,
            session_started_at=first.session_started_at,
        )
    )
    assert refreshed.session_id == first.session_id
    assert refreshed.jti != first.jti

    await revocation.revoke_session(redis, first.session_id)

    assert await revocation.is_revoked(redis, first) is True
    assert await revocation.is_revoked(redis, refreshed) is True


async def test_revoking_one_session_leaves_another_alone():
    redis = FakeRedis()
    laptop, phone = token(), token()

    await revocation.revoke_session(redis, laptop.session_id)

    assert await revocation.is_revoked(redis, laptop) is True
    assert await revocation.is_revoked(redis, phone) is False


async def test_revoking_a_missing_session_is_not_an_error():
    redis = FakeRedis()

    await revocation.revoke_session(redis, None)

    assert redis.values == {}


def test_a_token_carries_its_session_and_when_it_started():
    claims = token()

    assert claims.session_id
    assert claims.session_started_at


def test_signing_out_revokes_the_session_not_only_the_token():
    import ast
    import inspect

    from app.api import auth as auth_api

    tree = ast.parse(inspect.getsource(auth_api.logout).lstrip())
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            node.value = ast.Constant(value="")

    assert "revoke_session" in ast.unparse(tree)


def test_the_refresh_rotates_the_old_token():
    """Additive refresh leaves every previous token alive, so a captured one
    stays useful for its full life. Rotating means it dies the moment the real
    client next refreshes."""
    import ast
    import inspect

    from app.api import auth as auth_api

    tree = ast.parse(inspect.getsource(auth_api.refresh).lstrip())
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            node.value = ast.Constant(value="")

    assert "revoke_token" in ast.unparse(tree)


def test_the_refresh_is_capped_from_the_original_sign_in():
    """Without an absolute limit, refreshing forever and being signed in
    forever are the same thing -- which is what a 24-hour token was trying to
    avoid."""
    import ast
    import inspect

    from app.api import auth as auth_api

    tree = ast.parse(inspect.getsource(auth_api.refresh).lstrip())
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            node.value = ast.Constant(value="")
    body = ast.unparse(tree)

    assert "MAX_SESSION_DAYS" in body
    # From `sst`, not from this token's own iat.
    assert "session_started_at" in body
    assert auth_api.MAX_SESSION_DAYS <= 30


def test_the_refresh_rereads_the_user():
    """A role change, a disabled account or a removed membership must take
    effect on refresh rather than persisting for as long as somebody keeps
    refreshing."""
    import ast
    import inspect

    from app.api import auth as auth_api

    tree = ast.parse(inspect.getsource(auth_api.refresh).lstrip())
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            node.value = ast.Constant(value="")
    body = ast.unparse(tree)

    assert "find_user" in body
    assert "resolve_login" in body
    assert "is_active" in body


def test_the_dashboard_reads_the_expiry_from_the_token():
    """Hard-coding "now plus 24 hours" in the browser would drift the moment
    the server's TTL changed, and drift silently: the refresh would fire too
    late and the user would be signed out anyway."""
    from pathlib import Path

    auth_ts = (Path(__file__).resolve().parents[2] / "dashboard" / "auth.ts").read_text()

    assert "function expiryOf" in auth_ts
    assert "accessTokenExpires" in auth_ts
    assert "apiAuth.refresh" in auth_ts
