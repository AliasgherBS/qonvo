"""Tenant configuration — persona, providers, hours, escalation (DESIGN.md §10 Settings).

``ConfigUpdateRequest``/``_config_to_dict`` are also imported by ``app.api.admin``
for the ops-console equivalent (``PUT /api/admin/tenants/{id}/config``) so both
surfaces validate and serialize identically.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_claims, get_db, require_owner, require_tenant
from app.core.limits import (
    MAX_CUSTOM_INSTRUCTIONS,
    MAX_PAYMENT_DETAILS,
    MAX_PERSONA,
    exceeded,
)
from app.core.security import TokenClaims
from app.core.tenant_time import is_valid_timezone, tenant_timezone
from app.models.tenant import Tenant, TenantConfig
from app.services import audit
from app.services.audit import changed_fields

router = APIRouter(prefix="/api/config", tags=["config"])


class ConfigUpdateRequest(BaseModel):
    persona: str | None = None
    business_name: str | None = None
    primary_language: str | None = None
    tone: str | None = None
    custom_instructions: str | None = None
    #: IANA name, e.g. "Asia/Karachi". Governs opening hours and bookings both
    #: (teardown B1/N1/V2).
    timezone: str | None = None
    business_hours: dict | None = None
    owner_alert_number: str | None = None
    escalation_rules: dict | None = None
    llm_provider: str | None = None
    llm_model: str | None = None
    payment_details: str | None = None
    voice_reply_mode: str | None = None  # "match" | "always" | "never"
    # "match", "en", or a language the owner typed. Open on purpose: which
    # languages work is a property of the model, not of Qonvo.
    reply_language_mode: str | None = None
    # Owner notification preference: alert the owner when the bot hands a
    # conversation off to a human. Stored in escalation_rules (no column).
    notify_on_handoff: bool | None = None

    # --- length caps (spec §2) --------------------------------------------- #
    # Rejected, never truncated. Silently dropping the end of someone's
    # instructions is worse than refusing them: the save appears to work and the
    # rep quietly stops following the rules that got cut.
    #
    # Only a value the caller actually sent is checked. A tenant already over a
    # newly-lowered cap keeps working and is only asked to fix it when they next
    # edit that field, which is what "grandfather on read, enforce on write"
    # means in practice.
    @field_validator("custom_instructions")
    @classmethod
    def _cap_custom_instructions(cls, v: str | None) -> str | None:
        if v is not None and len(v) > MAX_CUSTOM_INSTRUCTIONS:
            raise exceeded("Custom instructions", limit=MAX_CUSTOM_INSTRUCTIONS, actual=len(v))
        return v

    @field_validator("persona")
    @classmethod
    def _cap_persona(cls, v: str | None) -> str | None:
        if v is not None and len(v) > MAX_PERSONA:
            raise exceeded("Persona", limit=MAX_PERSONA, actual=len(v))
        return v

    @field_validator("payment_details")
    @classmethod
    def _cap_payment_details(cls, v: str | None) -> str | None:
        if v is not None and len(v) > MAX_PAYMENT_DETAILS:
            raise exceeded("Payment details", limit=MAX_PAYMENT_DETAILS, actual=len(v))
        return v

    @field_validator("voice_reply_mode")
    @classmethod
    def _validate_voice_reply_mode(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if v not in {"match", "always", "never"}:
            raise ValueError("voice_reply_mode must be match, always, or never")
        return v

    @field_validator("reply_language_mode")
    @classmethod
    def _validate_reply_language_mode(cls, v: str | None) -> str | None:
        if v is None:
            return v
        from app.agent.language import MAX_LANGUAGE_WORDS, is_valid, sanitise_language

        if not is_valid(v):
            raise ValueError(
                "reply_language_mode must be 'match', 'en', or a language name "
                f"of at most {MAX_LANGUAGE_WORDS} words"
            )
        # Store the tidied form, so what the model is told is what was validated.
        return v if v in ("match", "en") else sanitise_language(v)

    @field_validator("owner_alert_number")
    @classmethod
    def _validate_owner_alert_number(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if not v or not v.replace("+", "").isdigit():
            raise ValueError("owner_alert_number must be digits with an optional leading +")
        return v

    @field_validator("primary_language")
    @classmethod
    def _validate_primary_language(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip().lower()
        if not v or len(v) > 16:
            raise ValueError("primary_language must be a short language code (e.g. 'en')")
        return v


class ConfigResponse(BaseModel):
    persona: str | None
    business_name: str | None
    languages: list
    primary_language: str
    tone: str | None
    custom_instructions: str | None
    timezone: str
    business_hours: dict
    owner_alert_number: str | None
    escalation_rules: dict
    llm_provider: str | None
    llm_model: str | None
    payment_details: str | None
    voice_reply_mode: str
    reply_language_mode: str
    notify_on_handoff: bool


def _config_to_dict(row: TenantConfig) -> ConfigResponse:
    return ConfigResponse(
        persona=row.persona,
        business_name=row.business_name,
        languages=row.languages,
        primary_language=row.primary_language,
        tone=row.tone,
        custom_instructions=row.custom_instructions,
        # The resolved value, not the raw column: a tenant whose timezone only
        # ever existed in the business_hours JSON should see that in the
        # control, not "UTC" (teardown B1).
        timezone=tenant_timezone(row),
        business_hours=row.business_hours,
        owner_alert_number=row.owner_alert_number,
        escalation_rules=row.escalation_rules,
        llm_provider=row.llm_provider,
        llm_model=row.llm_model,
        payment_details=row.payment_details,
        voice_reply_mode=((row.providers or {}).get("voice") or {}).get("mode") or "match",
        reply_language_mode=(
            ((row.providers or {}).get("language") or {}).get("mode") or "match"
        ),
        # Default on: the owner is alerted on handoff unless they opt out.
        notify_on_handoff=(row.escalation_rules or {}).get("notify_on_handoff", True),
    )


def _apply_config_update(row: TenantConfig, body: ConfigUpdateRequest) -> None:
    data = body.model_dump(exclude_unset=True)
    # Validated here rather than trusted, because an unknown name would be
    # stored happily and then silently resolve back to UTC -- the owner would
    # see their choice saved and their opening hours still wrong, which is the
    # same invisible failure this whole change is fixing.
    if data.get("timezone") is not None and not is_valid_timezone(data["timezone"]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{data['timezone']!r} is not a known timezone",
        )
    # These two aren't columns — they live in JSON maps. Pop before the column loop.
    voice_mode = data.pop("voice_reply_mode", None)
    language_mode = data.pop("reply_language_mode", None)
    notify_on_handoff = data.pop("notify_on_handoff", None)
    for field, value in data.items():
        setattr(row, field, value)
    if voice_mode is not None:
        providers = dict(row.providers or {})
        providers["voice"] = {**(providers.get("voice") or {}), "mode": voice_mode}
        row.providers = providers  # reassign so SQLAlchemy flags the JSONB change
    if language_mode is not None:
        providers = dict(row.providers or {})
        providers["language"] = {**(providers.get("language") or {}), "mode": language_mode}
        row.providers = providers
    if notify_on_handoff is not None:
        # Merge into escalation_rules AFTER the column loop, so an escalation_rules
        # value in the same request doesn't clobber this key. Reassign for JSONB.
        rules = dict(row.escalation_rules or {})
        rules["notify_on_handoff"] = notify_on_handoff
        row.escalation_rules = rules


async def _get_or_create_config(db: AsyncSession, tenant_id: UUID) -> TenantConfig:
    row = (
        await db.execute(select(TenantConfig).where(TenantConfig.tenant_id == tenant_id))
    ).scalar_one_or_none()
    if row is None:
        row = TenantConfig(tenant_id=tenant_id)
        db.add(row)
        await db.flush()
    return row


@router.get("", response_model=ConfigResponse)
async def get_config(
    tenant_id: UUID = Depends(require_tenant),
    db: AsyncSession = Depends(get_db),
) -> ConfigResponse:
    row = await _get_or_create_config(db, tenant_id)
    return _config_to_dict(row)


@router.put("", response_model=ConfigResponse)
async def update_config(
    body: ConfigUpdateRequest,
    # Owner-only: this accepts payment_details, the text the bot reads out
    # verbatim when a customer asks how to pay.
    tenant_id: UUID = Depends(require_owner),
    claims: TokenClaims = Depends(get_claims),
    db: AsyncSession = Depends(get_db),
) -> ConfigResponse:
    row = await _get_or_create_config(db, tenant_id)
    # Computed before the update is applied, because afterwards there is
    # nothing left to compare against.
    changed = changed_fields(row, body.model_dump(exclude_unset=True))
    _apply_config_update(row, body)
    # Keep the tenant's display name in sync with the business name edited here —
    # the topbar/JWT read Tenant.name, so otherwise the two silently diverge.
    if "business_name" in body.model_dump(exclude_unset=True) and body.business_name:
        await db.execute(
            update(Tenant).where(Tenant.id == tenant_id).values(name=body.business_name.strip())
        )
    await db.flush()
    if changed:
        # Field names only. `payment_details` is the text the rep reads out
        # verbatim when a customer asks how to pay, and a staff seat
        # substituting their own account number was the whole of teardown X1 --
        # so "who changed payment_details, and when" is exactly the record
        # needed, and the value itself is not.
        await audit.record(
            db,
            tenant_id=tenant_id,
            claims=claims,
            action="config_updated",
            target=str(tenant_id),
            meta={"fields": changed},
        )
    return _config_to_dict(row)


# --------------------------------------------------------------------------- #
# What the rep can actually do (teardown P1)
# --------------------------------------------------------------------------- #
# The Skills page listed no skills. The registry and its gating metadata have
# always existed server-side, so this is the read that turns them into
# something an owner can see: what they bought, and which of it is waiting on a
# connection they have not made.
#
# It lives on the config router rather than in a module of its own because a
# new router would have to be registered in app.main, and this is one read.
#
# Owner-facing copy, keyed by skill name. The registry's own descriptions are
# written *for the model* ("Use this once you have at least a phone number"),
# which is the wrong voice for a page whose job is to tell a salon owner what
# their rep does. A skill added to the registry without an entry here still
# appears, described by its registry text, rather than silently vanishing from
# the list.
SKILL_COPY: dict[str, tuple[str, str]] = {
    "capture_lead": (
        "Capture a lead",
        "Takes a name and number from someone who is interested but not ready, "
        "so you can follow up.",
    ),
    "human_handoff": (
        "Hand over to a person",
        "Stops answering and alerts you when a customer asks for a human, or asks "
        "something your rep cannot answer.",
    ),
    "check_availability": (
        "Check availability",
        "Reads your calendar before offering a time, so it never offers a slot you "
        "are already busy in.",
    ),
    "book_appointment": (
        "Book an appointment",
        "Puts a confirmed appointment on your calendar and confirms it to the customer.",
    ),
    "take_order": (
        "Take an order",
        "Records what a customer wants, item by item, and confirms it back to them.",
    ),
    "share_payment_details": (
        "Share payment details",
        "Sends your receiving account exactly as you wrote it when a customer asks "
        "how to pay.",
    ),
    "append_to_sheet": (
        "Log to your spreadsheet",
        "Adds a row to the Google Sheet you picked, for anything you want kept "
        "outside Qonvo.",
    ),
    "lookup_sheet": (
        "Look something up",
        "Searches the Google Sheet you picked for stock, prices or an order status, "
        "and only reports what is actually in it.",
    ),
}

#: Plain-language reason a gated skill is not available yet, by integration.
INTEGRATION_NEEDS: dict[str, str] = {
    "google_calendar": "Connect Google Calendar",
    "google_sheets": "Connect Google Sheets",
}

#: Same, for a skill gated on a config field the owner has not filled in.
CONFIG_KEY_NEEDS: dict[str, str] = {
    "payment_details": "Add your payment details",
}


class SkillInfo(BaseModel):
    key: str
    label: str
    description: str
    #: Whether the rep would be offered this tool on the next message.
    available: bool
    requires_integration: str | None = None
    requires_config_key: str | None = None
    #: What to do about it, when it is not available. None when it is.
    needs: str | None = None


def skill_states(
    definitions: dict[str, Any],
    *,
    ready: set[str],
    config_row: Any,
    configured: dict[str, bool],
) -> list[SkillInfo]:
    """Turn the registry plus this tenant's state into rows for the page.

    Pure, and separate from the route, because the interesting part is the
    availability rule and it must agree exactly with
    :func:`app.skills.registry.enabled_skill_names` -- the page telling an owner
    a skill is live while the pipeline never offers it is worse than the page
    not existing. Same three conditions, in the same order.
    """
    rows: list[SkillInfo] = []
    for name, definition in definitions.items():
        label, description = SKILL_COPY.get(name, (name.replace("_", " "), definition.description))
        needs: str | None = None
        # An explicit skills row with enabled=False wins over everything; no
        # row at all means enabled (the registry's default).
        if configured.get(name, True) is not True:
            needs = "Turned off for this workspace"
        elif definition.requires_integration and definition.requires_integration not in ready:
            needs = INTEGRATION_NEEDS.get(
                definition.requires_integration,
                f"Connect {definition.requires_integration}",
            )
        elif definition.requires_config_key and not getattr(
            config_row, definition.requires_config_key, None
        ):
            needs = CONFIG_KEY_NEEDS.get(
                definition.requires_config_key,
                f"Set {definition.requires_config_key.replace('_', ' ')}",
            )
        rows.append(
            SkillInfo(
                key=name,
                label=label,
                description=description,
                available=needs is None,
                requires_integration=definition.requires_integration,
                requires_config_key=definition.requires_config_key,
                needs=needs,
            )
        )
    return rows


@router.get("/skills", response_model=list[SkillInfo])
async def list_skills(
    # A read, and one a staff seat genuinely needs: somebody working the inbox
    # has to be able to see what the rep will and will not do on its own.
    tenant_id: UUID = Depends(require_tenant),
    db: AsyncSession = Depends(get_db),
) -> list[SkillInfo]:
    """Every built-in skill, with whether this tenant's rep can use it."""
    # Imported here rather than at module scope: the registry pulls in the
    # integration resolver and every handler, and app.api.admin imports this
    # module for its own config surface.
    from app.integrations.resolver import ready_providers
    from app.models.skill import Skill
    from app.skills.registry import SKILL_REGISTRY

    rows = (
        await db.execute(select(Skill.key, Skill.enabled).where(Skill.tenant_id == tenant_id))
    ).all()
    return skill_states(
        SKILL_REGISTRY,
        ready=await ready_providers(db, tenant_id),
        config_row=await _get_or_create_config(db, tenant_id),
        configured=dict(rows),
    )


__all__ = ["ConfigUpdateRequest", "SkillInfo", "router", "skill_states"]
