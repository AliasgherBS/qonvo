"""Authentication service: password login + JWT minting (DESIGN.md §8).

Login runs against the global ``users`` table (not tenant-scoped) plus the user's
``tenant_users`` membership, so it must use a session that can see across tenants
(the caller passes the system session). The minted JWT carries ``sub`` (email),
``tenant_id``, ``role``, and the cross-tenant ``qonvo_admin`` flag, consumed by
``app.core.security.decode_jwt`` on every subsequent request.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
import secrets
from dataclasses import dataclass
from uuid import UUID, uuid4

import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.plans import TRIAL_PLAN, get_plan
from app.core.config import settings
from app.core.logging import logger
from app.core.security import (
    ACCESS_TOKEN_TYPE,
    TokenError,
    decrypt_secret,
    hash_password,
    verify_password,
)
from app.core.totp import STEP_SECONDS, verify_code
from app.models.enums import UserRole
from app.models.tenant import Tenant, TenantConfig, TenantUser, User

# Self-serve signups get a free trial; after it ends the tenant is gated until
# it's on a paid plan (§9 billing).
TRIAL_DAYS = 14
# Hard message cap for a trial tenant — bounds LLM/voice spend for a free signup
# (the date check alone left trials able to burn unlimited credits for 14 days).
TRIAL_MESSAGE_QUOTA = get_plan(TRIAL_PLAN).entitlements["monthly_message_quota"]

# Password-reset links expire after this long.
PASSWORD_RESET_TTL_MINUTES = 30

# Verification links live much longer than reset links, because the two are
# reached differently. A reset is something you asked for thirty seconds ago; a
# verification mail arrives during signup and is often opened on a phone, later,
# after the tab has been closed. Thirty minutes here would mostly generate
# support requests, and the link proves control of a mailbox rather than
# granting a session.
EMAIL_VERIFICATION_TTL_HOURS = 24


def _password_fingerprint(user: User) -> str:
    """A short token that changes whenever the user's password changes.

    Embedding it in a reset link makes the link single-use and self-invalidating:
    once the password is set (by this reset or any change), outstanding links no
    longer match. Stateless — no reset-token table needed.
    """
    base = f"{user.id}:{user.hashed_password or 'none'}"
    return hashlib.sha256(base.encode()).hexdigest()[:16]


def create_password_reset_token(user: User) -> str:
    now = dt.datetime.now(dt.UTC)
    payload = {
        "sub": user.email,
        "typ": "pwreset",
        "pwf": _password_fingerprint(user),
        "iat": now,
        "exp": now + dt.timedelta(minutes=PASSWORD_RESET_TTL_MINUTES),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def read_password_reset_token(token: str) -> tuple[str, str] | None:
    """Return ``(email, password_fingerprint)`` if the token is a valid, unexpired
    reset token, else ``None``. The caller re-checks the fingerprint against the
    live user to enforce single-use."""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError:
        return None
    if payload.get("typ") != "pwreset":
        return None
    email, pwf = payload.get("sub"), payload.get("pwf")
    if not isinstance(email, str) or not isinstance(pwf, str):
        return None
    return email, pwf


def _verification_fingerprint(user: User) -> str:
    """A short token that changes once the address is verified.

    Same trick as :func:`_password_fingerprint`, and for the same reason: it
    makes the link single-use with no verification-token table to expire or
    clean up. Once ``email_verified`` flips, every outstanding link stops
    matching.

    The email is in the fingerprint too, so changing the address also
    invalidates a pending link rather than leaving one that would verify an
    address the account no longer has.
    """
    base = f"{user.id}:{user.email}:{user.email_verified}"
    return hashlib.sha256(base.encode()).hexdigest()[:16]


def create_email_verification_token(user: User) -> str:
    now = dt.datetime.now(dt.UTC)
    payload = {
        "sub": user.email,
        "typ": "emailverify",
        "evf": _verification_fingerprint(user),
        "iat": now,
        "exp": now + dt.timedelta(hours=EMAIL_VERIFICATION_TTL_HOURS),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def read_email_verification_token(token: str) -> tuple[str, str] | None:
    """Return ``(email, fingerprint)`` for a valid, unexpired verification
    token, else ``None``. The caller re-checks the fingerprint against the live
    user to enforce single-use.

    The ``typ`` check is the whole reason these are separate functions: a reset
    token and a verification token are both signed with the same key, so
    without it either would satisfy the other. ``decode_token`` used to have
    this gap for access tokens.
    """
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError:
        return None
    if payload.get("typ") != "emailverify":
        return None
    email, evf = payload.get("sub"), payload.get("evf")
    if not isinstance(email, str) or not isinstance(evf, str):
        return None
    return email, evf


async def verify_email(db: AsyncSession, token: str) -> User | None:
    """Consume a verification token and mark the address verified.

    Returns the user so the caller can sign them in, which is what makes this
    pleasant to use: clicking the link in the mail lands you in the product
    rather than on a page telling you to go and log in.

    Idempotent from the user's point of view but not replayable: a second click
    on the same link finds ``email_verified`` already true, so the fingerprint
    no longer matches and this returns ``None``. That is the correct answer for
    a link that has done its job.
    """
    parsed = read_email_verification_token(token)
    if parsed is None:
        return None
    email, evf = parsed
    user = await find_user(db, email)
    if user is None or not user.is_active or _verification_fingerprint(user) != evf:
        return None
    user.email_verified = True
    await db.flush()
    return user


async def change_password(db: AsyncSession, user: User, current: str, new: str) -> bool:
    """Set a new password after verifying the current one. False if it's wrong."""
    if not verify_password(current, user.hashed_password):
        return False
    user.hashed_password = hash_password(new)
    await db.flush()
    return True


async def reset_password(db: AsyncSession, token: str, new: str) -> bool:
    """Consume a reset token and set the new password. False if invalid/used."""
    parsed = read_password_reset_token(token)
    if parsed is None:
        return False
    email, pwf = parsed
    user = await find_user(db, email)
    # Fingerprint mismatch = the password already changed since the link was
    # issued (link reused or superseded) → reject.
    if user is None or not user.is_active or _password_fingerprint(user) != pwf:
        return False
    user.hashed_password = hash_password(new)
    # Using this link proves control of the mailbox, which is the same proof the
    # verification link asks for. Not recording it would leave somebody who
    # reset their password still nagged to confirm an address they just
    # demonstrably read mail at, and would leave the only route back from the
    # Google 409 a dead end for anyone who had forgotten their password.
    user.email_verified = True
    await db.flush()
    return True


@dataclass(frozen=True, slots=True)
class AuthResult:
    """Resolved identity for a successful login."""

    user: User
    tenant_id: UUID | None
    tenant_name: str | None
    role: str | None
    is_qonvo_admin: bool


def create_access_token(
    *,
    subject: str,
    tenant_id: UUID | None,
    role: str | None,
    is_qonvo_admin: bool,
    expires_in_hours: int | None = None,
    acting_as: str | None = None,
) -> str:
    """Mint a signed JWT with tenant/role claims and a ``jwt_expiry_hours`` TTL.

    ``expires_in_hours`` overrides that TTL, and exists so the dev seed script
    can mint a week-long token *through this function* rather than beside it.
    Two hand-rolled copies of this payload have now drifted from it: one missed
    ``typ`` when that became required and 401'd every seeded token, and one
    missed ``jti`` and made the token silently unrevocable. There is one minting
    function for that reason.

    ``acting_as`` marks the token as an impersonation and names the real actor,
    following the ``act`` claim from RFC 8693. Support could already mint an
    owner-scoped token for any tenant, and the token carried the owner's
    identity and nothing else -- so the act of impersonating was audited and
    everything done inside the session was attributed to the customer
    (teardown X4).
    """
    now = dt.datetime.now(dt.UTC)
    payload: dict = {
        "sub": subject,
        # A unique id, so one session can be revoked without touching the
        # others. Without it, signing out cleared the browser's copy and left
        # the credential valid for the rest of its 24 hours (teardown X6).
        "jti": uuid4().hex,
        # Says which kind of credential this is. decode_jwt requires it, so a
        # token minted for another purpose cannot authenticate a request even
        # though it is signed with the same secret.
        "typ": ACCESS_TOKEN_TYPE,
        "role": role,
        "qonvo_admin": is_qonvo_admin,
        # Only on access tokens. The reset and verification tokens are decoded
        # by plain jwt.decode with no audience argument, and PyJWT raises
        # InvalidAudienceError for a token that *carries* aud when none is
        # expected -- so adding these there would break every reset link.
        "aud": settings.jwt_audience,
        "iss": settings.jwt_issuer,
        "iat": now,
        # RFC 8693's shape for "somebody is acting on behalf of somebody else".
        **({"act": {"sub": acting_as}} if acting_as else {}),
        "exp": now
        + dt.timedelta(hours=expires_in_hours or settings.jwt_expiry_hours),
    }
    if tenant_id is not None:
        payload["tenant_id"] = str(tenant_id)
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


async def _resolve_membership(
    db: AsyncSession, user_id: UUID
) -> tuple[UUID, str, str | None] | None:
    """Return ``(tenant_id, role, tenant_name)`` for the user's first membership."""
    row = (
        await db.execute(
            select(TenantUser.tenant_id, TenantUser.role, Tenant.name)
            .join(Tenant, Tenant.id == TenantUser.tenant_id)
            .where(TenantUser.user_id == user_id)
            .order_by(TenantUser.created_at)
            .limit(1)
        )
    ).first()
    if row is None:
        return None
    tenant_id, role, tenant_name = row
    return tenant_id, str(role), tenant_name


async def authenticate(db: AsyncSession, email: str, password: str) -> AuthResult | None:
    """Verify credentials and resolve the acting tenant.

    Returns ``None`` for an unknown email, a bad password, or an inactive user —
    the route maps every ``None`` to a single 401 so the response does not reveal
    which check failed.
    """
    user = (
        await db.execute(select(User).where(User.email == email.lower().strip()))
    ).scalar_one_or_none()
    if user is None or not user.is_active:
        return None
    if not verify_password(password, user.hashed_password):
        return None

    membership = await _resolve_membership(db, user.id)
    if membership is None:
        # A qonvo_admin may legitimately have no tenant membership.
        return AuthResult(
            user=user,
            tenant_id=None,
            tenant_name=None,
            role=None,
            is_qonvo_admin=user.is_qonvo_admin,
        )
    tenant_id, role, tenant_name = membership
    return AuthResult(
        user=user,
        tenant_id=tenant_id,
        tenant_name=tenant_name,
        role=role,
        is_qonvo_admin=user.is_qonvo_admin,
    )


def slugify(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "biz"
    # random suffix keeps the globally-unique slug constraint collision-free.
    return f"{base}-{secrets.token_hex(3)}"


async def find_user(db: AsyncSession, email: str) -> User | None:
    return (
        await db.execute(select(User).where(User.email == email.lower().strip()))
    ).scalar_one_or_none()


async def resolve_login(db: AsyncSession, user: User) -> AuthResult:
    """Wrap an already-identified user as an :class:`AuthResult`.

    Shared by password login and Google SSO so both resolve the acting tenant the
    same way — including the qonvo_admin case, which legitimately has no
    membership.
    """
    membership = await _resolve_membership(db, user.id)
    if membership is None:
        return AuthResult(
            user=user,
            tenant_id=None,
            tenant_name=None,
            role=None,
            is_qonvo_admin=user.is_qonvo_admin,
        )
    tenant_id, role, tenant_name = membership
    return AuthResult(
        user=user,
        tenant_id=tenant_id,
        tenant_name=tenant_name,
        role=role,
        is_qonvo_admin=user.is_qonvo_admin,
    )


async def provision_tenant(
    db: AsyncSession,
    *,
    business_name: str,
    owner_name: str | None,
    email: str,
    password: str | None = None,
    email_verified: bool = False,
    timezone: str | None = None,
) -> AuthResult:
    """Create a tenant + config + owner user + membership on a free trial.

    ``password=None`` is the Google-SSO case. ``users.hashed_password`` is nullable
    and ``verify_password`` returns False for a null hash, so such an account
    simply can't be signed into with a password — no placeholder hash needed.

    ``timezone`` is the browser's, passed by the signup form. Absent or
    unrecognised falls through to the column default of UTC, so an older client
    is no worse off than it was.

    ``email_verified`` has no safe default, so it defaults to the safe one.
    Google has already proven the address by the time this is reached from that
    path, and passing True there is correct; self-serve signup has proven
    nothing and must leave it False until the mail is clicked. Required
    explicitly at both call sites rather than inferred from ``password is
    None``, because "no password" and "address proven" are two different facts
    that only coincide today.

    Cross-tenant by nature (there is no tenant yet), so callers pass the system
    session.
    """
    business_name = business_name.strip()
    tenant = Tenant(
        name=business_name,
        slug=slugify(business_name),
        status="active",
        plan="trial",
        trial_ends_at=dt.datetime.now(dt.UTC) + dt.timedelta(days=TRIAL_DAYS),
        # Stated rather than left to the column default, which is the same
        # value. warmup_stage was dead code for exactly this reason: a model
        # default is not a default when the caller always supplies the field,
        # and the next person to add a keyword here would not know this one was
        # load-bearing. The rep starts off; the owner turns it on when ready.
        rep_active=False,
    )
    db.add(tenant)
    await db.flush()
    db.add(
        TenantConfig(
            tenant_id=tenant.id,
            business_name=business_name,
            # Trial tenants get a hard message cap so a free signup can't burn
            # unlimited LLM/voice credits (enforced by the pipeline's quota gate).
            # Derived from the plan catalogue so the trial's entitlements can
            # never drift from what /api/billing/plans advertises.
            entitlements={**get_plan(TRIAL_PLAN).entitlements},
            # The browser's timezone when the signup form sent one. Every
            # tenant used to start on UTC, which made opening hours refuse
            # customers during business hours and put bookings five hours out
            # (teardown B1/N1). Falls back to the column default.
            **({"timezone": timezone} if timezone else {}),
        )
    )

    user = User(
        email=email.lower().strip(),
        hashed_password=hash_password(password) if password else None,
        full_name=(owner_name or "").strip() or None,
        email_verified=email_verified,
    )
    db.add(user)
    await db.flush()
    db.add(TenantUser(tenant_id=tenant.id, user_id=user.id, role=UserRole.owner))
    await db.flush()

    return AuthResult(
        user=user,
        tenant_id=tenant.id,
        tenant_name=tenant.name,
        role=UserRole.owner.value,
        is_qonvo_admin=False,
    )


__all__ = [
    "TRIAL_DAYS",
    "AuthResult",
    "authenticate",
    "change_password",
    "create_access_token",
    "create_email_verification_token",
    "create_password_reset_token",
    "find_user",
    "provision_tenant",
    "read_email_verification_token",
    "read_password_reset_token",
    "reset_password",
    "resolve_login",
    "slugify",
    "totp_code_replayed",
    "verify_email",
    "verify_totp_for",
]


# --------------------------------------------------------------------------- #
# Second factor (teardown X4)
# --------------------------------------------------------------------------- #
def verify_totp_for(user: User, code: str | None) -> bool:
    """Whether ``code`` is a valid second factor for this user.

    The secret is decrypted here and nowhere else. A decryption failure means
    the Fernet key was rotated without re-encrypting, and the honest answer to
    "is this code valid" is then no -- returning True would turn a key mistake
    into an authentication bypass.
    """
    if not user.totp_enabled or not user.totp_secret:
        return False
    try:
        secret = decrypt_secret(user.totp_secret)
    except TokenError:
        logger.error(f"could not decrypt the totp secret for {user.email}")
        return False
    return verify_code(secret, code)


async def totp_code_replayed(client, email: str, code: str | None) -> bool:
    """True when this exact code has already been used by this account.

    A code stays valid for its window, so without this a code read over
    somebody's shoulder, or captured from a phished form, works a second time
    within the same minute. ``SET NX`` makes the check and the claim one
    operation, so two simultaneous logins cannot both win.

    Fails **closed**: if the store is unreachable the code is treated as
    replayed. The opposite of the revocation check's trade, and for the
    opposite reason -- there, failing closed locks everybody out of a working
    product; here, failing open silently removes the protection at exactly the
    moment somebody might be attacking. The cost of being wrong is one refused
    login on an account that has another code thirty seconds later.
    """
    if not code:
        return True
    key = f"totp:used:{hashlib.sha256(email.strip().lower().encode()).hexdigest()[:32]}:{code}"
    try:
        # A window either side of now, so the key must outlive the widest code
        # still acceptable.
        claimed = await client.set(key, "1", ex=STEP_SECONDS * 3, nx=True)
    except Exception as exc:  # noqa: BLE001 - see the docstring
        logger.error(f"could not check for a replayed totp code: {exc}")
        return True
    return not claimed
