"""``capture_lead`` skill: record a prospective customer (DESIGN.md §7)."""

from __future__ import annotations

from typing import Any

from app.models.business import Lead
from app.skills.registry import SkillContext, SkillDefinition

_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "Customer's name, if given."},
        "phone": {
            "type": "string",
            "description": "Customer's phone number (required to follow up).",
        },
        "intent": {
            "type": "string",
            "description": "What the customer is interested in / asking about.",
        },
    },
    "required": ["phone"],
}


async def handle(ctx: SkillContext, args: dict[str, Any]) -> dict[str, Any]:
    phone = (args.get("phone") or "").strip()
    name = (args.get("name") or "").strip() or None
    intent = (args.get("intent") or "").strip() or None

    if not phone:
        return {
            "status": "error",
            "message": "A phone number is required to capture a lead.",
        }

    lead = Lead(
        tenant_id=ctx.tenant_id,
        conversation_id=ctx.conversation_id,
        name=name,
        phone=phone,
        notes=intent,
        data={"intent": intent} if intent else {},
    )
    ctx.db.add(lead)
    await ctx.db.flush()

    return {
        "status": "captured",
        "lead_id": str(lead.id),
        "message": "Thanks! We've noted your details and someone from the team will follow up.",
    }


DEFINITION = SkillDefinition(
    name="capture_lead",
    description=(
        "Record a prospective customer's contact details and interest so the "
        "business can follow up. Use this once you have at least a phone number."
    ),
    parameters=_PARAMETERS,
    handler=handle,
)

__all__ = ["DEFINITION", "handle"]
