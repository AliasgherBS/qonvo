"""Improve with AI, for the custom instructions field (functional test §04).

One route: ``POST /api/behavior/instructions/review``. It takes the text the
owner currently has on screen, sends it to *their own* configured model once,
and hands back a repaired version plus a list of what changed. It writes
nothing. The owner reads the two side by side, accepts or discards, and saves
the form the way they always do.

**Nothing is saved here, by design.** The most powerful field in the product
is the one an owner is least able to check, and an assistant that quietly
rewrote it would be worse than no assistant at all: the owner would stop
recognising their own instructions and would have no way to tell which of the
rep's behaviours came from them. So this route is a read that costs money, not
a write, and the accept step lives in the browser where the original is still
on screen.

**It costs the owner's own API credit**, since it runs on the tenant's
provider and key. Hence: one call per press, never on a timer and never in the
background, a per-tenant rate limit, a bounded input, and the tokens recorded
against the tenant's usage like any other model call. Requirement 4 asked for
a tight output cap too, and the provider adapter takes no ``max_tokens``, so
the cap is stated in the prompt and enforced after the fact by
``parse_suggestion``. Passing a real one through
``OpenAICompatProvider.generate`` is a one-line change in a file this stream
does not own.

**It degrades honestly.** Every failure path leaves the owner's text untouched
and says which failure it was: out of quota, key rejected, too slow, or an
answer we refuse to show. A partial generation is never presented as a
suggestion.
"""

from __future__ import annotations

import asyncio
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.instruction_review import (
    MAX_INPUT_CHARS,
    UnusableSuggestion,
    build_messages,
    detect_conflicts,
    parse_suggestion,
)
from app.api.deps import get_db, get_redis_dep, require_owner
from app.core import throttle
from app.core.limits import MAX_CUSTOM_INSTRUCTIONS
from app.core.logging import logger
from app.core.throttle import Throttle
from app.integrations.resolver import STATE_OK, credential_state
from app.models.skill import Integration
from app.models.tenant import TenantConfig
from app.providers.openai_compat import ProviderError, ProviderTimeout
from app.providers.registry import resolve_llm

router = APIRouter(prefix="/api/behavior", tags=["behavior"])


#: Ten presses an hour, per tenant.
#:
#: The shape of the work is: press, read the changes, edit a line by hand,
#: press again. Ten covers that loop several times over without a real reviewer
#: ever meeting the limit, and it bounds a stuck button, a double-click storm
#: or a script to ten small calls rather than to the owner's whole balance.
#: Per tenant rather than per user, because the credit is the tenant's and two
#: owners sharing a workspace share one bill.
INSTRUCTION_REVIEW = Throttle("instruction_review", limit=10, window_seconds=60 * 60)

#: An interactive press. The provider's own timeout plus retries can run to
#: well over a minute, which is fine for a background worker and not for
#: somebody watching a button spin. Past this we say it was too slow, which is
#: both true and more useful than a stall.
REVIEW_TIMEOUT_SECONDS = 45.0


class ReviewRequest(BaseModel):
    """The text on screen, which is not necessarily the text in the database.

    Sent by the client rather than read from ``tenant_config`` on purpose: the
    owner may be halfway through an edit, and reviewing a stale saved version
    while a different draft sits in the textarea would produce a suggestion
    that does not match what they are looking at.
    """

    instructions: str = Field(default="")


class ChangeOut(BaseModel):
    kind: str
    summary: str


class ReviewResponse(BaseModel):
    improved: str
    changes: list[ChangeOut]
    #: So the browser can render the counter against the same numbers the API
    #: validated with, instead of mirroring the cap a second time.
    characters: int
    limit: int
    #: True when the model found nothing to repair. A distinct answer, not an
    #: error: "your instructions look fine" is worth the press.
    unchanged: bool


def _refuse(code: str, message: str, *, http_status: int) -> HTTPException:
    """A refusal the dashboard can both render and branch on.

    Structured, because the browser shows ``message`` verbatim and a 5xx would
    otherwise be flattened into "Server error" by the shared client, which
    would turn "your provider is out of quota" into a message that blames us.
    """
    return HTTPException(status_code=http_status, detail={"code": code, "message": message})


async def _connected_providers(db: AsyncSession, tenant_id: UUID) -> list[str]:
    """Which integrations this tenant actually has, from our own rows.

    No Google call: the question is what the owner connected, and that is
    recorded here. ``credential_state`` is the same check the skills gate on,
    so "connected" means the same thing on this screen as it does in a
    conversation.
    """
    rows = (
        (await db.execute(select(Integration).where(Integration.tenant_id == tenant_id)))
        .scalars()
        .all()
    )
    return [r.provider for r in rows if r.enabled and credential_state(r) == STATE_OK]


@router.post("/instructions/review", response_model=ReviewResponse)
async def review_instructions(
    body: ReviewRequest,
    tenant_id: UUID = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis_dep),
) -> ReviewResponse:
    """Review the owner's custom instructions with the tenant's own model.

    Owner-only, and it writes nothing: no audit row, because there is no state
    change to attribute (``tests/test_audit.py`` carries the reason beside the
    handler name). The save that follows an accepted suggestion is an ordinary
    ``PUT /api/config``, and that one is audited already.
    """
    text = body.instructions.strip()

    # Cheap refusals before the rate limit, so a press that could never work
    # neither spends a token nor burns an allowance.
    if not text:
        raise _refuse(
            "empty",
            "There are no instructions to improve yet. Write a few rules first, "
            "then press this again.",
            http_status=status.HTTP_400_BAD_REQUEST,
        )
    if len(text) > MAX_INPUT_CHARS:
        raise _refuse(
            "too_long_to_review",
            f"These instructions are {len(text):,} characters, which is more than "
            f"this review will read ({MAX_INPUT_CHARS:,}). Trim them and try again.",
            http_status=status.HTTP_400_BAD_REQUEST,
        )

    # The incrementing counter in ``throttle.check`` is the one it calls "ip";
    # the account counter is read rather than bumped, because there it only
    # ever counts failed logins. Here every press costs money whether or not
    # the model answers well, so the counter that has to move is the one that
    # moves on every request, keyed by tenant.
    if await throttle.check(redis, INSTRUCTION_REVIEW, ip=f"tenant:{tenant_id}", account=None):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "rate_limited",
                "message": (
                    f"You have used all {INSTRUCTION_REVIEW.limit} AI reviews for this "
                    "hour. Your instructions are untouched. Try again later, or edit "
                    "them by hand in the meantime."
                ),
            },
            headers={"Retry-After": str(INSTRUCTION_REVIEW.window_seconds)},
        )

    config = (
        await db.execute(select(TenantConfig).where(TenantConfig.tenant_id == tenant_id))
    ).scalar_one_or_none()
    connected = await _connected_providers(db, tenant_id)

    log = logger.bind(tenant_id=str(tenant_id))
    conflicts = detect_conflicts(text, connected=connected)
    messages = build_messages(
        text,
        business_name=getattr(config, "business_name", None),
        reply_language_mode=getattr(config, "reply_language_mode", None),
        connected=connected,
        conflicts=conflicts,
    )

    provider = resolve_llm(config)
    try:
        try:
            result = await asyncio.wait_for(
                provider.generate(messages), timeout=REVIEW_TIMEOUT_SECONDS
            )
        finally:
            await provider.aclose()
    # ``asyncio.wait_for`` raises the builtin TimeoutError on 3.11+;
    # ProviderTimeout is the adapter's own, raised when its retries are spent.
    # Both mean the same thing to the owner.
    except (TimeoutError, ProviderTimeout) as exc:
        log.warning(f"instruction review timed out: {exc}")
        raise _refuse(
            "llm_timeout",
            "Your AI provider did not answer in time. Your instructions are "
            "untouched. Try again in a moment.",
            http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
        ) from exc
    except ProviderError as exc:
        log.warning(f"instruction review failed: {exc}")
        raise _provider_refusal(exc) from exc

    log.info(
        "instruction review",
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
        flagged=len(conflicts),
    )
    await _record_spend(tenant_id, config, result)

    try:
        suggestion = parse_suggestion(result.text)
    except UnusableSuggestion as exc:
        log.warning(f"unusable instruction suggestion: {exc}")
        raise _refuse(
            "unusable_suggestion",
            f"The suggestion came back unusable ({exc}), so we did not offer it. "
            "Your instructions are untouched. Try again.",
            http_status=status.HTTP_502_BAD_GATEWAY,
        ) from exc

    return ReviewResponse(
        improved=suggestion.improved,
        changes=[ChangeOut(kind=c.kind, summary=c.summary) for c in suggestion.changes],
        characters=suggestion.characters,
        limit=MAX_CUSTOM_INSTRUCTIONS,
        # Compared against what was sent, not against the saved row, for the
        # same reason the text is sent at all.
        unchanged=suggestion.improved.strip() == text,
    )


def _provider_refusal(exc: ProviderError) -> HTTPException:
    """Name the provider failure, because the owner's next move depends on it.

    Out of quota has actually happened here: two customer messages were lost to
    a 429 "you exceeded your current quota". "Something went wrong" would send
    that owner to us instead of to their provider's billing page.
    """
    code = exc.status_code
    if code == 429:
        return _refuse(
            "llm_quota_exceeded",
            "Your AI provider refused the request: the quota or rate limit on your "
            "key is used up. Your instructions are untouched. Try again later, or "
            "top up with your provider.",
            http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    if code in (401, 403):
        return _refuse(
            "llm_auth_failed",
            "Your AI provider rejected the key configured for this workspace. Your "
            "instructions are untouched. Check the key under Settings.",
            http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return _refuse(
        "llm_unavailable",
        "Your AI provider could not be reached. Your instructions are untouched. "
        "Try again in a moment.",
        http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
    )


async def _record_spend(tenant_id: UUID, config: object, result: object) -> None:
    """Meter this call like any other model call.

    The press is charged to the tenant's own key the instant the provider
    answers, so leaving it out of usage would make the meter quietly wrong and
    make this feature look free. ``messages_in``/``messages_out`` stay at zero:
    no customer message was handled, and inflating the message count would
    corrupt the cost-per-conversation figure the analytics page reports.

    Imported lazily. ``app.workers.pipeline`` pulls in the skills registry and
    the send gateway, which an API process has no reason to load at import
    time, and this is the codebase's existing pattern for that.
    """
    try:
        from app.providers.registry import resolve_llm_identity
        from app.workers.pipeline import compute_cost, record_billed_usage

        provider_name, model = resolve_llm_identity(config)  # type: ignore[arg-type]
        prompt_tokens = getattr(result, "prompt_tokens", 0) or 0
        completion_tokens = getattr(result, "completion_tokens", 0) or 0
        await record_billed_usage(
            tenant_id,
            messages_in=0,
            messages_out=0,
            tokens=prompt_tokens + completion_tokens,
            cost=compute_cost(
                provider_name,
                model,
                prompt_tokens,
                completion_tokens,
                cached_tokens=getattr(result, "cached_tokens", 0) or 0,
            ),
        )
    except Exception as exc:  # noqa: BLE001 - metering must not fail the review
        # The same posture as ``record_billed_usage`` itself: an accounting
        # problem must not turn a working suggestion into an error.
        logger.bind(tenant_id=str(tenant_id)).warning(f"could not record review usage: {exc}")
