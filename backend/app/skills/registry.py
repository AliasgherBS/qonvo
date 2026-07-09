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


SkillHandler = Callable[[SkillContext, dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass(slots=True)
class SkillDefinition:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: SkillHandler

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
from app.skills.capture_lead import DEFINITION as _CAPTURE_LEAD  # noqa: E402
from app.skills.human_handoff import DEFINITION as _HUMAN_HANDOFF  # noqa: E402

SKILL_REGISTRY: dict[str, SkillDefinition] = {
    _CAPTURE_LEAD.name: _CAPTURE_LEAD,
    _HUMAN_HANDOFF.name: _HUMAN_HANDOFF,
}


async def enabled_skill_names(db: AsyncSession, tenant_id: uuid.UUID) -> set[str]:
    """Names of skills enabled for ``tenant_id``.

    A built-in with no explicit ``skills`` row is enabled by default (MVP
    behavior — "never miss a customer" should work with zero manual config);
    an explicit row's ``enabled`` flag always wins.
    """
    rows = (
        await db.execute(select(Skill.key, Skill.enabled).where(Skill.tenant_id == tenant_id))
    ).all()
    configured = dict(rows)
    return {
        name
        for name in SKILL_REGISTRY
        if configured.get(name, True) is True
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
