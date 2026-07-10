"""Skill registry: OpenAI tool schemas + idempotent async handlers (DESIGN.md §7).

A skill is a named tool with a JSON schema (for the LLM tool-calling API) and
an async handler. Every mutating call carries an idempotency key
(``{conversation_id}:{tool_call_id}``); :func:`execute_skill` checks
``skill_executions`` before running the handler so at-least-once job delivery
never double-executes a write (DESIGN.md §5.3, §7).
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.skill import Skill, SkillExecution


@dataclass(slots=True)
class SkillContext:
    """Everything a handler needs, assembled by the pipeline per tool call."""

    db: AsyncSession
    tenant_id: uuid.UUID
    conversation_id: uuid.UUID
    idempotency_key: str
    conversation: Any | None = None
    tenant_config: Any | None = None
    send_gateway: Any | None = None
    session_name: str | None = None
    chat_id: str | None = None
    # Pre-resolved integration clients keyed by provider (tests / pipeline
    # injection); when absent, handlers build a real client from the DB.
    integration_clients: dict[str, Any] | None = None


SkillHandler = Callable[[SkillContext, dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass(slots=True)
class SkillDefinition:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: SkillHandler
    # When set, the skill is only offered to the model if the named integration
    # (see app.integrations) is connected and usable for the tenant.
    requires_integration: str | None = None
    # When set, the skill is only offered if the tenant's config has a truthy
    # value for this attribute (e.g. "payment_details" for share_payment_details).
    requires_config_key: str | None = None

    def tool_schema(self) -> dict[str, Any]:
        """OpenAI tools-API JSON schema for this skill."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


# Imported after the dataclasses above so each module can import them back
# (`from app.skills.registry import SkillContext, SkillDefinition`) without a
# circular-import failure.
from app.skills.append_to_sheet import DEFINITION as _APPEND_TO_SHEET  # noqa: E402
from app.skills.book_appointment import DEFINITION as _BOOK_APPOINTMENT  # noqa: E402
from app.skills.capture_lead import DEFINITION as _CAPTURE_LEAD  # noqa: E402
from app.skills.check_availability import DEFINITION as _CHECK_AVAILABILITY  # noqa: E402
from app.skills.human_handoff import DEFINITION as _HUMAN_HANDOFF  # noqa: E402
from app.skills.lookup_sheet import DEFINITION as _LOOKUP_SHEET  # noqa: E402
from app.skills.share_payment_details import DEFINITION as _SHARE_PAYMENT  # noqa: E402
from app.skills.take_order import DEFINITION as _TAKE_ORDER  # noqa: E402

SKILL_REGISTRY: dict[str, SkillDefinition] = {
    _CAPTURE_LEAD.name: _CAPTURE_LEAD,
    _HUMAN_HANDOFF.name: _HUMAN_HANDOFF,
    _BOOK_APPOINTMENT.name: _BOOK_APPOINTMENT,
    _APPEND_TO_SHEET.name: _APPEND_TO_SHEET,
    _CHECK_AVAILABILITY.name: _CHECK_AVAILABILITY,
    _LOOKUP_SHEET.name: _LOOKUP_SHEET,
    _TAKE_ORDER.name: _TAKE_ORDER,
    _SHARE_PAYMENT.name: _SHARE_PAYMENT,
}


async def enabled_skill_names(db: AsyncSession, tenant_id: uuid.UUID) -> set[str]:
    """Names of skills enabled for ``tenant_id``.

    A built-in with no explicit ``skills`` row is enabled by default (MVP
    behavior — "never miss a customer" should work with zero manual config);
    an explicit row's ``enabled`` flag always wins. A skill that
    ``requires_integration`` is additionally hidden until that integration is
    connected, so the model is never offered a tool that can't execute.
    """
    from app.integrations.resolver import ready_providers
    from app.models.tenant import TenantConfig

    rows = (
        await db.execute(select(Skill.key, Skill.enabled).where(Skill.tenant_id == tenant_id))
    ).all()
    configured = dict(rows)
    ready = await ready_providers(db, tenant_id)
    tenant_config = (
        await db.execute(select(TenantConfig).where(TenantConfig.tenant_id == tenant_id))
    ).scalar_one_or_none()

    def _config_ok(definition: SkillDefinition) -> bool:
        if definition.requires_config_key is None:
            return True
        return bool(getattr(tenant_config, definition.requires_config_key, None))

    return {
        name
        for name, definition in SKILL_REGISTRY.items()
        if configured.get(name, True) is True
        and (definition.requires_integration is None or definition.requires_integration in ready)
        and _config_ok(definition)
    }


async def enabled_tools(db: AsyncSession, tenant_id: uuid.UUID) -> list[dict[str, Any]]:
    """OpenAI tool schemas for every skill enabled for ``tenant_id``."""
    names = await enabled_skill_names(db, tenant_id)
    return [SKILL_REGISTRY[name].tool_schema() for name in names]


class UnknownSkillError(Exception):
    """Raised when a tool call names a skill outside the registry."""


async def execute_skill(
    ctx: SkillContext,
    name: str,
    args: dict[str, Any],
) -> dict[str, Any]:
    """Run ``name``'s handler, or return the cached result of a prior identical call."""
    definition = SKILL_REGISTRY.get(name)
    if definition is None:
        raise UnknownSkillError(f"unknown skill: {name}")

    existing = (
        await ctx.db.execute(
            select(SkillExecution).where(
                SkillExecution.tenant_id == ctx.tenant_id,
                SkillExecution.idempotency_key == ctx.idempotency_key,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing.result

    result = await definition.handler(ctx, args)

    ctx.db.add(
        SkillExecution(
            tenant_id=ctx.tenant_id,
            skill_key=name,
            idempotency_key=ctx.idempotency_key,
            conversation_id=ctx.conversation_id,
            status="completed",
            result=result,
        )
    )
    return result


__all__ = [
    "SKILL_REGISTRY",
    "SkillContext",
    "SkillDefinition",
    "SkillHandler",
    "UnknownSkillError",
    "enabled_skill_names",
    "enabled_tools",
    "execute_skill",
]
