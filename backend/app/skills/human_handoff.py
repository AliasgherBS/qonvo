"""``human_handoff`` skill: escalate to the business owner (DESIGN.md §5.5, §7)."""

from __future__ import annotations

from typing import Any

from app.core.logging import logger
from app.models.business import Handoff
from app.models.conversation import Conversation
from app.models.enums import ConversationState, NotificationType
from app.models.ops import Notification
from app.skills.registry import SkillContext, SkillDefinition

_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "reason": {
            "type": "string",
            "description": "Why the conversation needs a human (e.g. unanswerable question).",
        },
    },
    "required": ["reason"],
}


def _to_chat_id(number: str) -> str:
    return number if "@" in number else f"{number}@c.us"


async def handle(ctx: SkillContext, args: dict[str, Any]) -> dict[str, Any]:
    reason = (args.get("reason") or "").strip() or "Escalated by the agent."

    conversation = ctx.conversation
    if conversation is None:
        conversation = await ctx.db.get(Conversation, ctx.conversation_id)
    if conversation is not None:
        conversation.state = ConversationState.needs_human

    ctx.db.add(
        Handoff(
            tenant_id=ctx.tenant_id,
            conversation_id=ctx.conversation_id,
            reason=reason,
        )
    )
    ctx.db.add(
        Notification(
            tenant_id=ctx.tenant_id,
            type=NotificationType.escalation,
            title="A customer needs a human",
            body=reason,
            meta={"conversation_id": str(ctx.conversation_id)},
        )
    )

    owner_alert_number = getattr(ctx.tenant_config, "owner_alert_number", None)
    if owner_alert_number and ctx.send_gateway is not None and ctx.session_name:
        try:
            await ctx.send_gateway.send_text(
                ctx.session_name,
                _to_chat_id(owner_alert_number),
                f"A customer needs your attention: {reason}",
            )
        except Exception as exc:  # noqa: BLE001 — alert failure must not block handoff
            logger.bind(tenant_id=str(ctx.tenant_id)).warning(f"owner alert send failed: {exc}")

    # Best-effort email alert to the owner (transport is config-driven; §12.1).
    try:
        from app.services.email import email_owner

        await email_owner(
            ctx.db,
            ctx.tenant_id,
            subject="A customer needs a human",
            body=f"Your AI rep escalated a conversation.\n\nReason: {reason}",
        )
    except Exception as exc:  # noqa: BLE001 — email failure must not block handoff
        logger.bind(tenant_id=str(ctx.tenant_id)).warning(f"owner email failed: {exc}")

    return {"status": "escalated", "message": "team notified"}


DEFINITION = SkillDefinition(
    name="human_handoff",
    description=(
        "Escalate the conversation to a human team member. Use this when the "
        "customer explicitly asks for a person, or their question isn't covered "
        "by the business knowledge."
    ),
    parameters=_PARAMETERS,
    handler=handle,
)

__all__ = ["DEFINITION", "handle"]
