"""``capture_lead`` skill: record a prospective customer (DESIGN.md §7).

Never invoked once in the whole of the live period (E4). A booking exchange
collected a name, a phone number, a city and a service and captured nothing:
that lead exists only inside a WhatsApp transcript.

The cause was not here. Nothing in the assembled prompt had ever mentioned this
skill, and ``human_handoff`` -- the only skill the prompt did name, inside
``GROUNDING_INSTRUCTION`` -- is the only skill that has ever run. That is fixed
in ``pipeline.LEAD_CAPTURE_INSTRUCTION``.

Two things here made obeying that new instruction harder than it needed to be:

**Being told to call it whenever details appear must not produce a row every
time.** The execution ledger keys on the tool call id, so it stops a
*redelivery* double-writing but not a second, honest call on a later turn. One
lead per conversation, enriched as more is learnt, is what an owner means by
"a lead".

**The number was treated as something the model has to supply.** The customer
is messaging from a WhatsApp number, so the chat id *is* a phone number, and a
"capture Ali, wants a facial" call used to be refused for lacking the one
detail the system already had. It now falls back to the chat's own number,
exactly as ``take_order`` has always done, so a name on its own is enough.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.models.business import Lead
from app.skills.registry import SkillContext, SkillDefinition

_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "Customer's name, if given."},
        "phone": {
            "type": "string",
            "description": (
                "Customer's phone number if they gave one. Leave it out to use "
                "the WhatsApp number they are messaging from."
            ),
        },
        "intent": {
            "type": "string",
            "description": "What the customer is interested in / asking about.",
        },
    },
    "required": ["phone"],
}


def _phone_from_chat_id(chat_id: str | None) -> str | None:
    """The customer's own number, out of the WhatsApp chat id.

    Same shape as ``take_order._phone_from_chat_id``: "923001234567@c.us" and
    "…@lid" both carry the number in front of the "@".
    """
    if not chat_id:
        return None
    return chat_id.split("@", 1)[0] or None


async def handle(ctx: SkillContext, args: dict[str, Any]) -> dict[str, Any]:
    phone = (args.get("phone") or "").strip() or _phone_from_chat_id(ctx.chat_id)
    name = (args.get("name") or "").strip() or None
    intent = (args.get("intent") or "").strip() or None
    # The WhatsApp push name, when the model passed none. It is what the inbox
    # already labels the conversation with, so a nameless lead is a worse
    # record than one carrying the name the customer chose for themselves.
    if name is None and ctx.conversation is not None:
        name = (getattr(ctx.conversation, "customer_name", None) or "").strip() or None

    if not phone:
        # Only reachable with no chat id at all, which in the pipeline cannot
        # happen: a lead with no way to reach the person is not a lead.
        return {
            "status": "error",
            "message": "A phone number is required to capture a lead.",
        }

    existing = (
        await ctx.db.execute(
            select(Lead)
            .where(Lead.conversation_id == ctx.conversation_id)
            .order_by(Lead.created_at)
            .limit(1)
        )
    ).scalar_one_or_none()
    if isinstance(existing, Lead):
        # Enrich, never overwrite with less. A later turn that finally learns
        # the name should fill it in; one that has dropped the intent must not
        # blank what an earlier turn recorded.
        existing.name = existing.name or name
        existing.phone = existing.phone or phone
        if intent and intent != existing.notes:
            existing.notes = f"{existing.notes}\n{intent}" if existing.notes else intent
            existing.data = {**(existing.data or {}), "intent": intent}
        await ctx.db.flush()
        return {
            "status": "captured",
            "lead_id": str(existing.id),
            "message": "Already noted for this customer; the details have been updated.",
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
        "business can follow up. Call this as soon as you have a name, or as "
        "soon as the customer asks you to arrange anything, whatever else you "
        "are doing in the same turn. You do not need to ask for their phone "
        "number; leave it out and the number they are messaging from is used. "
        "Calling it more than once in a conversation is safe: it keeps one "
        "record and adds to it."
    ),
    parameters=_PARAMETERS,
    handler=handle,
)

__all__ = ["DEFINITION", "handle"]
