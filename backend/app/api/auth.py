"""Login + current-user profile (DESIGN.md §8).

Both routes are cross-tenant lookups (email -> user -> membership), so they run
against the ``qonvo_system`` BYPASSRLS session via ``get_system_db`` rather than
a tenant-scoped one — there is no tenant to scope by until the token/credentials
resolve one.
"""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_claims, get_system_db
from app.core import throttle
from app.core.config import settings
from app.core.passwords import MAX_LENGTH, PasswordRejected, check_password
from app.core.redis import get_redis
from app.core.revocation import revoke_all_for_subject, revoke_session, revoke_token
from app.core.security import TokenClaims, TokenError, decrypt_secret, encrypt_secret
from app.core.signup_guard import is_disposable_email
from app.core.tenant_time import is_valid_timezone
from app.core.totp import generate_secret, provisioning_uri, verify_code
from app.core.validation import QuietValidationRoute
from app.models.tenant import Tenant, User
from app.services.auth import (
    AuthResult,
    authenticate,
    change_password,
    create_access_token,
    create_email_verification_token,
    create_password_reset_token,
    find_user,
    provision_tenant,
    read_password_reset_token,
    reset_password,
    resolve_login,
    totp_code_replayed,
    verify_email,
    verify_totp_for,
)
from app.services.email import (
    send_password_reset_email,
    send_verification_email,
    send_welcome_email,
)
from app.services.google_identity import GoogleIdentityError, verify_google_id_token

#: ``route_class`` because a 422 here used to hand back the password.
#: pydantic's ``missing`` error sets ``input`` to the *whole* submitted body,
#: so leaving any one field out of a signup returned every other field --
#: verified: ``POST /api/auth/signup`` without ``owner_name`` came back 422
#: with the plaintext password in it, and ``reset-password`` did the same with
#: the reset token. Unauthenticated, so anything logging 4xx bodies collected
#: them (F10).
router = APIRouter(prefix="/api", tags=["auth"], route_class=QuietValidationRoute)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    #: The six-digit code, for an account with a second factor enabled.
    #:
    #: Optional in the schema and required in effect: the login path refuses an
    #: enrolled account without a valid one. Optional here so the client can
    #: make one call, be told a code is needed, and ask for it -- rather than
    #: the form having to know in advance whether this address has 2FA, which
    #: would be an enumeration oracle.
    totp_code: str | None = None


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str | None
    tenant_id: str | None
    name: str | None
    #: On every sign-in rather than only at signup: the banner asking somebody
    #: to confirm their address has to appear when they come back tomorrow, not
    #: just in the tab they signed up in.
    email_verified: bool = True


class MeResponse(BaseModel):
    email: str
    name: str | None
    role: str | None
    tenant_id: str | None
    tenant_name: str | None
    email_verified: bool = True


def _login_response(result: AuthResult) -> LoginResponse:
    """Mint the JWT and shape the response for any successful identification."""
    token = create_access_token(
        subject=result.user.email,
        tenant_id=result.tenant_id,
        role=result.role,
        is_qonvo_admin=result.is_qonvo_admin,
    )
    # A cross-tenant superadmin has no tenant membership role, so surface the
    # admin flag *as* the role — the dashboard gates admin nav/routes on
    # role === "qonvo_admin" (an admin otherwise arrives with role null and is
    # bounced off every /admin page onto a tenant-less, broken /inbox).
    effective_role = "qonvo_admin" if result.is_qonvo_admin else result.role
    return LoginResponse(
        access_token=token,
        role=effective_role,
        tenant_id=str(result.tenant_id) if result.tenant_id else None,
        name=result.user.full_name,
        email_verified=result.user.email_verified,
    )


@router.post("/auth/login", response_model=LoginResponse)
async def login(
    body: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_system_db),
) -> LoginResponse:
    redis = get_redis()
    if await throttle.check(
        redis, throttle.LOGIN, ip=throttle.client_ip(request), account=body.email
    ):
        # 429 with a Retry-After rather than a 401. Telling an attacker they are
        # rate limited costs nothing they could not measure anyway, and telling
        # a real user "invalid password" when the password was right sends them
        # to reset a password that works.
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="too many attempts, try again shortly",
            headers={"Retry-After": str(throttle.LOGIN.window_seconds)},
        )

    result = await authenticate(db, body.email, body.password)
    if result is None:
        await throttle.record_failure(redis, throttle.LOGIN, account=body.email)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid email or password",
        )
    # The second factor, checked after the password (teardown X4).
    #
    # After, deliberately. Asking for a code before the password is right would
    # tell an attacker which addresses have 2FA enabled, and asking for it at
    # all for an account without one would tell them the opposite.
    if result.user.totp_enabled:
        if not verify_totp_for(result.user, body.totp_code):
            # The failure counts against the account, like a wrong password:
            # otherwise a correct password plus unlimited code guesses is a
            # million tries at six digits.
            await throttle.record_failure(redis, throttle.LOGIN, account=body.email)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "code": "totp_required" if not body.totp_code else "totp_invalid",
                    "message": (
                        "Enter the six-digit code from your authenticator app."
                        if not body.totp_code
                        else "That code is not right, or it has expired. Try the next one."
                    ),
                },
            )
        if await totp_code_replayed(get_redis(), result.user.email, body.totp_code):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "code": "totp_replayed",
                    "message": "That code has already been used. Wait for the next one.",
                },
            )

    # Forget the failures. Otherwise someone who mistypes nine times and then
    # succeeds stays one mistake from being locked out for the rest of the hour.
    await throttle.clear(redis, throttle.LOGIN, account=body.email)
    return _login_response(result)


class SignupRequest(BaseModel):
    business_name: str = Field(min_length=1, max_length=255)
    owner_name: str = Field(min_length=1, max_length=255)
    email: EmailStr
    # Length is not asserted here. `check_password` owns the whole policy, and
    # splitting it between a Pydantic constraint and a validator means two
    # different error shapes for the same rule -- a 422 with a field error for
    # one character too few, and a 400 with sentences for anything else.
    password: str = Field(max_length=MAX_LENGTH)
    #: The browser's own timezone, sent by the signup form.
    #:
    #: Taken here rather than left to a settings page nobody visits. The
    #: alternative was every tenant starting on UTC, which is what made
    #: opening hours and bookings both silently wrong (teardown B1/N1). An
    #: unrecognised or absent value falls back to UTC, so a client that does
    #: not send it is no worse off than before.
    timezone: str | None = Field(default=None, max_length=64)


@router.post("/auth/signup", response_model=LoginResponse, status_code=status.HTTP_201_CREATED)
async def signup(
    body: SignupRequest,
    request: Request,
    db: AsyncSession = Depends(get_system_db),
) -> LoginResponse:
    """Public self-serve registration: provisions a tenant + owner on a free
    trial and returns a token (auto-login). Admins can still create tenants via
    /admin/tenants. Cross-tenant (no tenant context yet) so it runs on the
    system session, like login."""
    # Throttled per IP: signup writes a tenant, a config row and a session slot,
    # so the cost of abuse is ours rather than a wasted guess. Not throttled per
    # account, since by definition the account does not exist yet.
    if await throttle.check(
        get_redis(), throttle.SIGNUP, ip=throttle.client_ip(request), account=None
    ):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="too many signups from this address, try again later",
            headers={"Retry-After": str(throttle.SIGNUP.window_seconds)},
        )

    email = body.email.lower().strip()
    if is_disposable_email(email):
        # A speed bump rather than a wall: anybody determined can register a
        # domain for a dollar. What it stops is the cheap version, where each
        # signup provisions a tenant, a config row and a session slot and
        # carries a trial quota that costs real credit (teardown X9).
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "disposable_email",
                "message": (
                    "Please sign up with your business email address. We need to be able "
                    "to reach you about your account."
                ),
            },
        )
    try:
        await check_password(
            body.password, email=email, business_name=body.business_name
        )
    except PasswordRejected as exc:
        raise _reject_weak(exc) from exc
    if await find_user(db, email):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="an account with this email already exists",
        )

    result = await provision_tenant(
        db,
        business_name=body.business_name,
        owner_name=body.owner_name,
        email=email,
        password=body.password,
        # Nothing has proven this address yet, and two sign-in paths resolve
        # accounts by email (teardown X2).
        email_verified=False,
        timezone=body.timezone if is_valid_timezone(body.timezone) else None,
    )
    # Confirmation now, welcome once confirmed. Two emails arriving together
    # compete with each other and the actionable one loses; the welcome's job is
    # to be excited about a working account, which this is not yet. It also
    # keeps us from mailing enthusiastic HTML at addresses that never asked for
    # it, which is what damages a young sending domain's reputation.
    await _send_verification(result.user)
    return _login_response(result)


def _reject_weak(exc: PasswordRejected) -> HTTPException:
    """One shape for every weak-password refusal.

    Every reason at once, and machine-readable, because the strength meter on
    the form needs to render them next to the field rather than as one toast.
    """
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"code": "weak_password", "reasons": exc.reasons},
    )


async def _send_verification(user: User) -> None:
    """Mail a confirmation link for this user's address."""
    token = create_email_verification_token(user)
    url = f"{settings.dashboard_base_url}/verify-email?token={token}"
    await send_verification_email(user.email, user.full_name, url)


class VerifyEmailRequest(BaseModel):
    token: str


@router.post("/auth/verify-email", response_model=LoginResponse)
async def verify_email_route(
    body: VerifyEmailRequest, db: AsyncSession = Depends(get_system_db)
) -> LoginResponse:
    """Confirm an address from the emailed link, and sign the user in.

    Returning a session rather than a bare 204 is the difference between
    clicking the link and being in the product, and clicking the link and being
    told to go and log in. The link is single-use, so this cannot be replayed:
    the token carries a fingerprint of the unverified state and stops matching
    the moment it succeeds.

    Deliberately not throttled by account, because guessing a token is not the
    attack it protects against: the token is a signed JWT, so an attacker who
    could forge one already has the signing key.
    """
    user = await verify_email(db, body.token)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This confirmation link is invalid, already used, or has expired.",
        )
    result = await resolve_login(db, user)
    # Now the account is real, so the welcome is worth sending.
    await send_welcome_email(user.email, user.full_name, result.tenant_name or "your business")
    return _login_response(result)


@router.post("/auth/resend-verification", status_code=status.HTTP_202_ACCEPTED)
async def resend_verification(
    request: Request,
    claims: TokenClaims = Depends(get_claims),
    db: AsyncSession = Depends(get_system_db),
) -> dict:
    """Send the confirmation link again, for the signed-in user only.

    Authenticated rather than taking an address in the body, which is the whole
    reason it is shaped this way: an endpoint that mails a link to any address
    given to it is a way to use us to send unsolicited mail to a third party,
    and that costs us our sending reputation rather than costing an attacker
    anything.

    Throttled on top of that, because a signed-in user holding the button down
    still sends real email.
    """
    if await throttle.check(
        get_redis(),
        throttle.PASSWORD_RESET,
        ip=throttle.client_ip(request),
        account=claims.subject,
    ):
        # 202 regardless, like forgot-password: the caller already knows their
        # own address exists, so the only thing a 429 adds here is a worse
        # experience for somebody who clicked twice.
        return {"status": "ok"}

    user = await find_user(db, claims.subject)
    if user is not None and user.is_active and not user.email_verified:
        await _send_verification(user)
    return {"status": "ok"}


class GoogleAuthRequest(BaseModel):
    id_token: str = Field(min_length=1)
    # Only used when this Google account is new here; otherwise ignored.
    business_name: str | None = Field(default=None, max_length=255)


@router.post("/auth/google", response_model=LoginResponse)
async def google_auth(
    body: GoogleAuthRequest, db: AsyncSession = Depends(get_system_db)
) -> LoginResponse:
    """Sign in (or sign up) with Google.

    Deliberately separate from the integrations OAuth flow. Both use the same
    Google client, but this one asks only for identity — merging them would demand
    Calendar permission from every new signup before they've seen the product,
    which is the fastest way to lose them. Calendar/Sheets consent is requested
    later, from the Integrations page, when the owner actually enables that
    feature (incremental authorization).

    Cross-tenant like login/signup, so it runs on the system session.
    """
    try:
        identity = await verify_google_id_token(body.id_token)
    except GoogleIdentityError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc

    user = await find_user(db, identity.email)
    if user is not None:
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="this account is disabled"
            )
        # The account pre-hijacking check (teardown X2). Google has proven the
        # address belongs to whoever is standing here; it has not proven that
        # *this row* does. A row with a password nobody has ever confirmed the
        # address for was created by somebody who typed the address in, and
        # signing into it would hand them everything the real owner does next:
        # their WhatsApp session, their knowledge base, every customer number.
        #
        # An unverified row with no password is a different thing entirely and
        # is safe to adopt: with no password there is no second way in, so
        # Google's assertion is the only credential that row has ever had.
        if not user.email_verified and user.hashed_password is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                # A machine-readable code, because the dashboard has to tell
                # these apart to offer the right next step, and matching on
                # prose breaks the first time the prose is improved.
                detail={
                    "code": "password_account_unverified",
                    "message": (
                        "An account with this email already exists and was created with a "
                        "password. Sign in with that password instead. If you have "
                        "forgotten it, reset it from the sign-in page and that will "
                        "confirm this address at the same time."
                    ),
                },
            )
        # Google asserted the address, so a row that only Google can reach is
        # now proven. Recording it means the WhatsApp gate opens for accounts
        # that never had a confirmation mail to click.
        if not user.email_verified:
            user.email_verified = True
            await db.flush()
        # Backfill a name for accounts created before they had one.
        if not user.full_name and identity.full_name:
            user.full_name = identity.full_name
            await db.flush()
        return _login_response(await resolve_login(db, user))

    # New Google account → provision a tenant, same as self-serve signup. Fall
    # back to the display name for the business, since the owner can rename it in
    # Settings and blocking signup for a missing field would be worse.
    business_name = (
        (body.business_name or "").strip()
        or identity.full_name
        or identity.email.split("@")[0]
    )
    result = await provision_tenant(
        db,
        business_name=business_name,
        owner_name=identity.full_name,
        email=identity.email,
        # Google verifies the address before asserting it, and
        # verify_google_id_token refuses an id_token whose email_verified claim
        # is false. So this address is proven and no confirmation mail is owed.
        email_verified=True,
        password=None,
    )
    await send_welcome_email(identity.email, identity.full_name, business_name)
    return _login_response(result)


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(max_length=MAX_LENGTH)


@router.post("/auth/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password_route(
    body: ChangePasswordRequest,
    claims: TokenClaims = Depends(get_claims),
    db: AsyncSession = Depends(get_system_db),
) -> None:
    """Change the signed-in user's password (verifies the current one)."""
    user = await find_user(db, claims.subject)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")
    try:
        await check_password(body.new_password, email=user.email)
    except PasswordRejected as exc:
        raise _reject_weak(exc) from exc
    if not await change_password(db, user, body.current_password, body.new_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Your current password is incorrect."
        )
    # Ending the sessions the old password opened is the one thing everybody
    # expects a password change to do, and it did not (teardown X6). The
    # caller's own token goes too, which is correct: if the reason for the
    # change is that somebody else had the password, the session they are
    # holding is the one that matters.
    await revoke_all_for_subject(get_redis(), user.email)


#: How long a sign-in may be extended before the password is asked for again.
#:
#: A refresh that never expires is a login that never expires, which is the
#: thing a 24-hour token was trying to avoid. Two weeks is a working
#: fortnight: long enough that nobody is interrupted mid-task, short enough
#: that a token quietly captured a month ago is dead.
MAX_SESSION_DAYS = 14


@router.post("/auth/refresh", response_model=LoginResponse)
async def refresh(
    claims: TokenClaims = Depends(get_claims),
    db: AsyncSession = Depends(get_system_db),
) -> LoginResponse:
    """Extend a live session without asking for the password again (teardown X6).

    The token lasts a day and nothing renewed it, so every owner was thrown
    back to the login screen once a day, mid-task. Aligning the dashboard's
    session to the token's life fixed the *lying* half of that -- a signed-in
    shell over a dead credential -- and left the interruption.

    Rotating, not additive: the presenting token is revoked as the new one is
    issued, so a captured token is only useful until the real client next
    refreshes, and a fork of the chain is visible as two tokens claiming one
    session.

    Capped at ``MAX_SESSION_DAYS`` from the *original* sign-in, which is what
    ``sst`` is for. Without an absolute limit, refreshing forever and being
    signed in forever are the same thing.

    Re-reads the user rather than trusting the token's claims: a role changed,
    an account disabled or a membership removed must take effect on refresh
    rather than persisting for as long as somebody keeps refreshing.
    """
    started = claims.session_started_at
    if started is not None and (
        int(dt.datetime.now(dt.UTC).timestamp()) - started > MAX_SESSION_DAYS * 86400
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "session_expired",
                "message": "Please sign in again.",
            },
        )

    user = await find_user(db, claims.subject)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="this account is not active"
        )

    result = await resolve_login(db, user)
    token = create_access_token(
        subject=result.user.email,
        tenant_id=result.tenant_id,
        role=result.role,
        is_qonvo_admin=result.is_qonvo_admin,
        acting_as=claims.acting_as,
        session_id=claims.session_id,
        session_started_at=started,
    )
    # Rotate: the old token stops working the moment the new one exists.
    await revoke_token(get_redis(), jti=claims.jti, expires_at=claims.raw.get("exp"))
    return LoginResponse(
        access_token=token,
        role="qonvo_admin" if result.is_qonvo_admin else result.role,
        tenant_id=str(result.tenant_id) if result.tenant_id else None,
        name=result.user.full_name,
        email_verified=result.user.email_verified,
    )


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(claims: TokenClaims = Depends(get_claims)) -> None:
    """Revoke the token that made this request (teardown X6).

    Signing out used to clear the browser's copy and leave the credential
    valid for the rest of its 24 hours, which is not what "sign out" means to
    anybody. This session only, not every session: signing out on a laptop must
    not sign the same person out on their phone.

    The *session* rather than the token. Once a session can be refreshed, one
    token is a link in a chain, and revoking the newest link stops whoever
    holds it while leaving anybody who forked the chain still inside.

    204 whatever happens. A sign-out that reports failure leaves somebody
    unsure whether they are signed out, and the client has already discarded
    its copy by the time it hears back.
    """
    redis = get_redis()
    await revoke_session(redis, claims.session_id)
    await revoke_token(redis, jti=claims.jti, expires_at=claims.raw.get("exp"))


@router.post("/auth/logout-everywhere", status_code=status.HTTP_204_NO_CONTENT)
async def logout_everywhere(claims: TokenClaims = Depends(get_claims)) -> None:
    """End every session this person has, on every device.

    The thing an owner reaches for after losing a phone, and one of the pieces
    the teardown found missing from the Account page entirely.

    Both mechanisms, not just the marker. The marker only catches tokens issued
    *strictly before* it, which is deliberate -- a password change issues a new
    session in the same request and must not revoke it. But this endpoint
    issues nothing, so a caller whose token happens to share the marker's
    second would stay signed in on the very device they pressed the button on.
    Caught live, at a one-second granularity.
    """
    redis = get_redis()
    await revoke_all_for_subject(redis, claims.subject)
    await revoke_token(redis, jti=claims.jti, expires_at=claims.raw.get("exp"))


# --------------------------------------------------------------------------- #
# Second factor: enrolment (teardown X4)
# --------------------------------------------------------------------------- #
class TotpStartResponse(BaseModel):
    secret: str
    provisioning_uri: str


class TotpConfirmRequest(BaseModel):
    code: str


@router.post("/auth/totp/start", response_model=TotpStartResponse)
async def totp_start(
    claims: TokenClaims = Depends(get_claims),
    db: AsyncSession = Depends(get_system_db),
) -> TotpStartResponse:
    """Issue a secret and the URI an authenticator app scans.

    Stored immediately but **not enabled**. Two columns rather than one
    nullable secret precisely so this half-finished state exists: somebody who
    starts enrolling, scans nothing and closes the tab must not be locked out
    of their own account.

    Re-callable. Starting again replaces the pending secret, which is what
    somebody does when they lose the tab or set up a new phone. It refuses once
    a factor is already in force, because replacing a live secret is a
    disable-then-enable and each step should require a code.
    """
    user = await find_user(db, claims.subject)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")
    if user.totp_enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "totp_already_enabled",
                "message": "Two-factor authentication is already on. Turn it off first.",
            },
        )

    secret = generate_secret()
    user.totp_secret = encrypt_secret(secret)
    await db.flush()
    return TotpStartResponse(
        secret=secret,
        provisioning_uri=provisioning_uri(secret, account=user.email),
    )


@router.post("/auth/totp/confirm", status_code=status.HTTP_204_NO_CONTENT)
async def totp_confirm(
    body: TotpConfirmRequest,
    claims: TokenClaims = Depends(get_claims),
    db: AsyncSession = Depends(get_system_db),
) -> None:
    """Turn the second factor on, once a code from it has been proved.

    Requiring a code before enabling is the whole point: enabling on the
    strength of having *issued* a secret locks out anybody whose app failed to
    scan it, and the person who finds out is locked out at the moment they need
    to sign in.
    """
    user = await find_user(db, claims.subject)
    if user is None or not user.totp_secret:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "totp_not_started", "message": "Start the setup again."},
        )
    if user.totp_enabled:
        return

    try:
        secret = decrypt_secret(user.totp_secret)
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "totp_not_started", "message": "Start the setup again."},
        ) from exc
    if not verify_code(secret, body.code):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "totp_invalid",
                "message": "That code is not right. Check your app and try the next one.",
            },
        )

    user.totp_enabled = True
    await db.flush()


@router.post("/auth/totp/disable", status_code=status.HTTP_204_NO_CONTENT)
async def totp_disable(
    body: TotpConfirmRequest,
    claims: TokenClaims = Depends(get_claims),
    db: AsyncSession = Depends(get_system_db),
) -> None:
    """Turn the second factor off, which itself requires a code.

    Otherwise a stolen session can remove the protection that would have made
    the session hard to steal, and the account is back to one password without
    the owner being asked anything.
    """
    user = await find_user(db, claims.subject)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")
    if not user.totp_enabled:
        return
    if not verify_totp_for(user, body.code):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "totp_invalid", "message": "That code is not right."},
        )

    user.totp_enabled = False
    user.totp_secret = None
    await db.flush()


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


@router.post("/auth/forgot-password", status_code=status.HTTP_202_ACCEPTED)
async def forgot_password_route(
    body: ForgotPasswordRequest,
    request: Request,
    db: AsyncSession = Depends(get_system_db),
) -> dict:
    """Email a password-reset link. Always returns 202 — never reveals whether an
    account exists (no user enumeration)."""
    # Throttled because each call sends an email. Unthrottled this is a way to
    # use us to spam a third party, which harms our sending reputation more than
    # it harms us. Still 202 when throttled, for the same reason the endpoint is
    # always 202: a different response here would reveal which addresses exist.
    if await throttle.check(
        get_redis(),
        throttle.PASSWORD_RESET,
        ip=throttle.client_ip(request),
        account=body.email,
    ):
        return {"status": "ok"}

    user = await find_user(db, body.email)
    if user is not None and user.is_active:
        token = create_password_reset_token(user)
        reset_url = f"{settings.dashboard_base_url}/reset-password?token={token}"
        await send_password_reset_email(user.email, user.full_name, reset_url)
    return {"status": "ok"}


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(max_length=MAX_LENGTH)


@router.post("/auth/reset-password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password_route(
    body: ResetPasswordRequest, db: AsyncSession = Depends(get_system_db)
) -> None:
    """Set a new password from a reset-link token (single-use, 30-min expiry)."""
    # Checked before the token is consumed, so a rejected password does not
    # burn the link and force another email.
    parsed_for_policy = read_password_reset_token(body.token)
    try:
        await check_password(
            body.new_password,
            email=parsed_for_policy[0] if parsed_for_policy else None,
        )
    except PasswordRejected as exc:
        raise _reject_weak(exc) from exc
    if not await reset_password(db, body.token, body.new_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This reset link is invalid or has expired.",
        )
    # A reset is the recovery path, so it is the most likely to be happening
    # *because* somebody else has access. Every outstanding session goes.
    # Re-read the token for its subject. It parses without a database round
    # trip, and the fingerprint check that made it single-use has already run
    # inside reset_password.
    parsed = read_password_reset_token(body.token)
    if parsed:
        await revoke_all_for_subject(get_redis(), parsed[0])


@router.get("/me", response_model=MeResponse)
async def me(
    claims: TokenClaims = Depends(get_claims),
    db: AsyncSession = Depends(get_system_db),
) -> MeResponse:
    user = (await db.execute(select(User).where(User.email == claims.subject))).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")

    tenant_name = None
    if claims.tenant_id is not None:
        tenant_name = (
            await db.execute(select(Tenant.name).where(Tenant.id == claims.tenant_id))
        ).scalar_one_or_none()

    return MeResponse(
        email=user.email,
        name=user.full_name,
        role="qonvo_admin" if claims.is_qonvo_admin else claims.role,
        tenant_id=str(claims.tenant_id) if claims.tenant_id else None,
        tenant_name=tenant_name,
        email_verified=user.email_verified,
    )


__all__ = ["router"]
